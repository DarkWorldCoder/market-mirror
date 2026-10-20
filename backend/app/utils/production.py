"""
production.py - Production Deployment Middleware, Security, Rate Limiting & Observability.

Features:
1. API Authentication (`MM_API_AUTH_TOKEN` / `API_AUTH_TOKEN`):
   - Bearer / `X-API-Key` authentication on `/api/*` and `/metrics` using constant-time comparison.
   - Failed attempts are rate limited per client (`MM_AUTH_FAIL_LIMIT`, default 10 per minute).
   - Zero-friction in local development when unset. In production (`MM_ENV=production`) a
     non-loopback bind refuses to start without it (see `Config.production_errors`).
2. Sliding-Window Rate Limiter (`MM_RATE_LIMIT_RPM`):
   - Per-client rate limiting on `/api/*` with `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After`.
   - The client is `request.remote_addr`. `X-Forwarded-For` is honoured only with
     `TRUST_PROXY_HEADERS=1`, where Werkzeug's `ProxyFix` rewrites `remote_addr` from the
     last proxy hop; a spoofed header is ignored otherwise.
   - Memory is bounded: idle clients are evicted and at most `MM_RATE_LIMIT_MAX_CLIENTS` are tracked.
3. Request Correlation IDs (`X-Request-ID`, validated: <= 64 chars of [A-Za-z0-9._:-]),
   Latency Timing (`X-Response-Time-Ms`), and Security Headers.
4. Production error hygiene: with `MM_ENV=production`, `traceback` fields and traceback text are
   removed from every JSON response and logged server-side with the request id instead.
5. Probes: public `/health` (liveness) and `/ready` (readiness, `{"ready": bool}` only);
   authenticated `/api/system/status` (details) and `/metrics` (Prometheus).
"""

from __future__ import annotations

import collections
import hmac
import json
import math
import os
import platform
import re
import shutil
import threading
import time
import uuid
from typing import Any, Deque, Dict, List, Optional, Tuple

from flask import Flask, g, jsonify, request, Response

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from .logger import get_logger

logger = get_logger("mirofish.production")

VERSION = "2.0.0"
_BOOT_TIME = time.time()
_METRICS_LOCK = threading.Lock()
_REQUEST_COUNTS: Dict[str, int] = collections.Counter()   # keyed by "METHOD <url rule>": bounded by the route table
_STATUS_COUNTS: Dict[int, int] = collections.Counter()
_LATENCIES_MS: Deque[float] = collections.deque(maxlen=2000)
_KNOWN_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

_RATE_LOCK = threading.Lock()
_RATE_WINDOWS: "collections.OrderedDict[str, Deque[float]]" = collections.OrderedDict()
_RATE_WINDOW_S = 60.0
_RATE_SWEEP_EVERY_S = 30.0
_rate_last_sweep = 0.0

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
_TRACEBACK_MARKER = "Traceback (most recent call last)"


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


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


def _auth_fail_limit(app: Flask) -> int:
    raw = app.config.get("MM_AUTH_FAIL_LIMIT")
    if raw is None:
        raw = os.environ.get("MM_AUTH_FAIL_LIMIT", "10")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 10


def _client_ip() -> str:
    """The peer address. With TRUST_PROXY_HEADERS=1, ProxyFix has already set it from X-Forwarded-For."""
    return request.remote_addr or "unknown"


def _request_id() -> str:
    incoming = (request.headers.get("X-Request-ID") or "").strip()
    if incoming and _REQUEST_ID_RE.match(incoming):
        return incoming
    return uuid.uuid4().hex[:16]


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


def _sweep_rate_windows(now: float) -> None:
    """Drop keys whose newest hit is older than the window (caller holds _RATE_LOCK)."""
    global _rate_last_sweep
    if now - _rate_last_sweep < _RATE_SWEEP_EVERY_S:
        return
    _rate_last_sweep = now
    cutoff = now - _RATE_WINDOW_S
    for key in [k for k, dq in _RATE_WINDOWS.items() if not dq or dq[-1] < cutoff]:
        del _RATE_WINDOWS[key]


def _window(key: str, now: float) -> Deque[float]:
    """The hit window for key, trimmed to the last minute (caller holds _RATE_LOCK)."""
    _sweep_rate_windows(now)
    dq = _RATE_WINDOWS.get(key)
    if dq is None:
        dq = collections.deque()
        _RATE_WINDOWS[key] = dq
        max_keys = _env_int("MM_RATE_LIMIT_MAX_CLIENTS", 10000, minimum=1)
        while len(_RATE_WINDOWS) > max_keys:
            _RATE_WINDOWS.popitem(last=False)   # least recently used
    else:
        _RATE_WINDOWS.move_to_end(key)
    window_start = now - _RATE_WINDOW_S
    while dq and dq[0] < window_start:
        dq.popleft()
    return dq


def _check_rate_limit(key: str, limit: int, record: bool = True) -> Tuple[bool, int, int]:
    """Return (allowed, remaining, retry_after_s). With record=False only checks."""
    now = time.monotonic()
    with _RATE_LOCK:
        if not record and key not in _RATE_WINDOWS:
            return True, limit, 0   # nothing recorded for this client: do not create an entry just to check
        dq = _window(key, now)
        if len(dq) >= limit:
            retry_after = max(1, int(math.ceil(_RATE_WINDOW_S - (now - dq[0]))))
            return False, 0, retry_after
        if record:
            dq.append(now)
        return True, max(0, limit - len(dq)), 0


def _record_hit(key: str) -> None:
    now = time.monotonic()
    with _RATE_LOCK:
        _window(key, now).append(now)


def _rate_limited_response(message: str, limit: int, retry_after: int) -> Response:
    resp = jsonify({
        "success": False,
        "error": message,
        "retry_after_seconds": retry_after,
        "request_id": getattr(g, "request_id", None),
    })
    resp.status_code = 429
    resp.headers["Retry-After"] = str(retry_after)
    resp.headers["X-RateLimit-Limit"] = str(limit)
    resp.headers["X-RateLimit-Remaining"] = "0"
    return resp


def _percentile(vals: List[float], pct: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, int(round((pct / 100.0) * (len(s) - 1)))))
    return round(s[idx], 2)


# --------------------------------------------------------------------------
# Readiness / status
# --------------------------------------------------------------------------

def _storage_checks() -> Tuple[bool, Dict[str, Any]]:
    checks: Dict[str, Any] = {}
    ok = True
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
            logger.warning(f"readiness: {label} is not writable: {e}")
            checks[label] = {"ok": False, "error": type(e).__name__}
            ok = False
    return ok, checks


def _llm_configured() -> bool:
    return bool(Config.LLM_API_KEY or Config.LLM_POOL)


def is_ready() -> bool:
    """Cheap readiness: storage writable and task store readable. No network calls."""
    storage_ok, _ = _storage_checks()
    return storage_ok and TaskManager().store_healthy()


def readiness_report() -> Dict[str, Any]:
    """Detailed readiness (authenticated callers only: it names paths' free space and the provider)."""
    ok, checks = _storage_checks()
    store_ok = TaskManager().store_healthy()
    checks["task_store"] = {"ok": store_ok}
    ok = ok and store_ok

    # Configuration only: no pool object is built here (a fresh pool has no call counters to report).
    checks["llm"] = {
        "configured": _llm_configured(),
        "provider": Config.LLM_PROVIDER,
        "model": Config.LLM_MODEL_NAME,
        "pool": [p.strip() for p in (Config.LLM_POOL or "").split(",") if p.strip()] or None,
    }
    return {
        "status": "ready" if ok else "degraded",
        "ready": ok,
        "version": VERSION,
        "uptime_seconds": round(time.time() - _BOOT_TIME, 1),
        "checks": checks,
    }


def _http_stats() -> Dict[str, Any]:
    with _METRICS_LOCK:
        lats = list(_LATENCIES_MS)
        total_reqs = sum(_STATUS_COUNTS.values())
        err_reqs = sum(c for code, c in _STATUS_COUNTS.items() if code >= 500)
        status_map = {str(k): v for k, v in sorted(_STATUS_COUNTS.items())}
        routes = dict(_REQUEST_COUNTS)
    return {
        "requests_total": total_reqs,
        "errors_5xx": err_reqs,
        "status_codes": status_map,
        "routes": routes,
        "latency_p50_ms": _percentile(lats, 50),
        "latency_p95_ms": _percentile(lats, 95),
    }


def _task_counts() -> Dict[str, int]:
    counts = TaskManager().count_by_status()
    return {
        "total": sum(counts.values()),
        "pending": counts.get(TaskStatus.PENDING.value, 0),
        "processing": counts.get(TaskStatus.PROCESSING.value, 0),
        "completed": counts.get(TaskStatus.COMPLETED.value, 0),
        "failed": counts.get(TaskStatus.FAILED.value, 0),
    }


def system_status_report() -> Dict[str, Any]:
    """Detailed production telemetry for `/api/system/status` (behind auth when a token is set)."""
    return {
        **readiness_report(),
        "environment": os.environ.get("MM_ENV", "development"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "http": _http_stats(),
        "tasks": _task_counts(),
    }


def prometheus_metrics_text() -> str:
    """Prometheus text exposition format for `/metrics` (only counters this process really keeps)."""
    http = _http_stats()
    tasks = _task_counts()
    lines = [
        "# HELP marketmirror_uptime_seconds Process uptime in seconds",
        "# TYPE marketmirror_uptime_seconds gauge",
        f"marketmirror_uptime_seconds {round(time.time() - _BOOT_TIME, 1)}",
        "# HELP marketmirror_ready Readiness state (1 = ready, 0 = degraded)",
        "# TYPE marketmirror_ready gauge",
        f"marketmirror_ready {1 if is_ready() else 0}",
        "# HELP marketmirror_http_requests_total Total HTTP requests handled",
        "# TYPE marketmirror_http_requests_total counter",
        f"marketmirror_http_requests_total {http['requests_total']}",
        "# HELP marketmirror_http_errors_total Total HTTP 5xx responses",
        "# TYPE marketmirror_http_errors_total counter",
        f"marketmirror_http_errors_total {http['errors_5xx']}",
        "# HELP marketmirror_http_latency_p95_ms 95th percentile HTTP latency in ms (last 2000 requests)",
        "# TYPE marketmirror_http_latency_p95_ms gauge",
        f"marketmirror_http_latency_p95_ms {http['latency_p95_ms']}",
        "# HELP marketmirror_tasks_count Tasks by status",
        "# TYPE marketmirror_tasks_count gauge",
    ]
    for st in ("pending", "processing", "completed", "failed"):
        lines.append(f'marketmirror_tasks_count{{status="{st}"}} {tasks.get(st, 0)}')
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Traceback scrubbing (production)
# --------------------------------------------------------------------------

def _scrub(value: Any, found: List[str]) -> Any:
    """Remove `traceback` keys and traceback text from a JSON value; collect what was removed."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "traceback":
                if v:
                    found.append(str(v))
                continue
            out[k] = _scrub(v, found)
        return out
    if isinstance(value, list):
        return [_scrub(v, found) for v in value]
    if isinstance(value, str) and _TRACEBACK_MARKER in value:
        found.append(value)
        lines = [ln.strip() for ln in value.strip().splitlines() if ln.strip()]
        return lines[-1] if lines else "Internal error"
    return value


def scrub_tracebacks_from_response(response: Response) -> Response:
    """Strip tracebacks from a JSON response body and log them server-side."""
    if response.direct_passthrough or response.is_streamed or not response.is_json:
        return response
    try:
        raw = response.get_data()
    except Exception:  # noqa: BLE001
        return response
    if b"traceback" not in raw and _TRACEBACK_MARKER.encode() not in raw:
        return response
    try:
        body = json.loads(raw)
    except ValueError:
        return response
    found: List[str] = []
    clean = _scrub(body, found)
    if not found:
        return response
    req_id = getattr(g, "request_id", "?")
    for tb in found:
        logger.error(f"[req={req_id}] {request.method} {request.path} error traceback (not sent to client):\n{tb}")
    response.set_data(json.dumps(clean, ensure_ascii=False))
    return response


# --------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------

def install_production_middleware(app: Flask) -> None:
    """Attach production auth, rate-limiting, request IDs, security headers, error handlers, and probes."""
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = _env_int("TRUST_PROXY_HOPS", 1, minimum=1)
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_prefix=hops)  # type: ignore[assignment]

    @app.before_request
    def _prod_before_request():
        g.request_id = _request_id()
        g.request_start_time = time.monotonic()

        # Public probes bypass auth & rate limits
        if request.path in ("/health", "/ready") or request.method == "OPTIONS":
            return None

        # /api/setup/* has its own stricter guard (this computer only + the setup token from ./mm setup)
        protected = (request.path.startswith("/api/") and not request.path.startswith("/api/setup/")) or request.path == "/metrics"
        ip = _client_ip()

        # 1. Optional per-client rate limiting (counts every /api request, authenticated or not)
        rpm = _rate_limit_rpm(app)
        if rpm > 0 and request.path.startswith("/api/"):
            allowed, remaining, retry_after = _check_rate_limit(f"rpm:{ip}", rpm)
            g.rate_limit_rpm = rpm
            g.rate_limit_remaining = remaining
            if not allowed:
                return _rate_limited_response(f"Rate limit exceeded ({rpm} requests/minute)", rpm, retry_after)

        # 2. API key / Bearer token authentication, with failed attempts rate limited
        expected = _auth_token(app)
        if expected and protected:
            fail_limit = _auth_fail_limit(app)
            fail_key = f"authfail:{ip}"
            if fail_limit > 0:
                allowed, _, retry_after = _check_rate_limit(fail_key, fail_limit, record=False)
                if not allowed:
                    logger.warning(f"[req={g.request_id}] auth lockout for {ip}")
                    return _rate_limited_response("Too many failed authentication attempts", fail_limit, retry_after)
            if not _check_auth(expected):
                if fail_limit > 0:
                    _record_hit(fail_key)
                return jsonify({
                    "success": False,
                    "error": "Unauthorized: valid API key or Bearer token required",
                    "request_id": g.request_id,
                }), 401
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
            rule = request.url_rule.rule if request.url_rule is not None else "<unmatched>"
            method = request.method if request.method in _KNOWN_METHODS else "OTHER"
            with _METRICS_LOCK:
                _LATENCIES_MS.append(elapsed_ms)
                _REQUEST_COUNTS[f"{method} {rule}"] += 1
                _STATUS_COUNTS[response.status_code] += 1
        if hasattr(g, "rate_limit_rpm"):
            response.headers.setdefault("X-RateLimit-Limit", str(g.rate_limit_rpm))
            response.headers.setdefault("X-RateLimit-Remaining", str(getattr(g, "rate_limit_remaining", 0)))

        if Config.is_production():
            response = scrub_tracebacks_from_response(response)

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
        original = getattr(err, "original_exception", None) or err
        logger.error(
            f"Unhandled 500 error [req={getattr(g, 'request_id', '?')}]: {original!r}",
            exc_info=(type(original), original, original.__traceback__) if isinstance(original, BaseException) else None,
        )
        return jsonify({"success": False, "error": "Internal server error", "request_id": getattr(g, "request_id", None)}), 500

    @app.route("/ready", methods=["GET"])
    def ready_probe():
        ok = is_ready()
        return jsonify({"ready": ok}), (200 if ok else 503)

    @app.route("/api/system/status", methods=["GET"])
    def api_system_status():
        return jsonify({"success": True, "data": system_status_report()})

    @app.route("/metrics", methods=["GET"])
    def prometheus_metrics():
        return Response(prometheus_metrics_text(), mimetype="text/plain; version=0.0.4; charset=utf-8")

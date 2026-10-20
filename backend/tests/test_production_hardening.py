"""Production hardening: shutdown, startup refusal, rate limiting, probes, CLI auth, task store, tracebacks."""

import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

import pytest
import requests

from app import create_app
from app.config import Config
from app.models.task import SERVER_RESTARTED_ERROR, TaskManager, TaskStatus
from app.utils import production

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

TOKEN = "t0k3n-" + "a" * 40
SECRET = "s3cr3t-" + "b" * 40


@pytest.fixture(autouse=True)
def _clean_production_state(monkeypatch):
    for key in ("MM_ENV", "MM_API_AUTH_TOKEN", "API_AUTH_TOKEN", "CORS_ORIGINS", "TRUST_PROXY_HEADERS",
                "MM_RATE_LIMIT_RPM", "MM_AUTH_FAIL_LIMIT", "MM_RATE_LIMIT_MAX_CLIENTS", "SECRET_KEY", "FLASK_DEBUG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FLASK_HOST", "127.0.0.1")
    with production._RATE_LOCK:
        production._RATE_WINDOWS.clear()
    yield
    with production._RATE_LOCK:
        production._RATE_WINDOWS.clear()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _production_env(monkeypatch, host="127.0.0.1"):
    monkeypatch.setenv("MM_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("FLASK_HOST", host)


# ---------------------------------------------------------------------------
# 1. SIGTERM: shutdown from another thread, chained handler, simulations stopped
# ---------------------------------------------------------------------------

def test_sigterm_stops_server_chains_previous_handler_and_kills_simulations(monkeypatch):
    import run
    from app.services.simulation_runner import SimulationRunner

    app = create_app()
    server = run.BoundedThreadedWSGIServer("127.0.0.1", 0, app, max_threads=4)
    port = server.server_address[1]
    sim = subprocess.Popen(["sleep", "60"], start_new_session=True)
    sim_id = "sim_shutdown_test_" + str(os.getpid())
    old_handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    chained = []
    monkeypatch.setattr(SimulationRunner, "_cleanup_done", False)
    SimulationRunner._processes[sim_id] = sim
    try:
        signal.signal(signal.SIGTERM, lambda signum, frame: chained.append(signum))
        run.install_shutdown_handlers(server)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        assert requests.get(f"http://127.0.0.1:{port}/health", timeout=5).status_code == 200

        started = time.monotonic()
        os.kill(os.getpid(), signal.SIGTERM)
        serving.join(timeout=10)
        assert not serving.is_alive(), "serve_forever did not return after SIGTERM"
        assert time.monotonic() - started < 8
        assert chained == [signal.SIGTERM], "the previously installed handler was not chained"
        assert sim.wait(timeout=5) is not None, "simulation subprocess still running"
    finally:
        for s, h in old_handlers.items():
            signal.signal(s, h)
        SimulationRunner._processes.pop(sim_id, None)
        if sim.poll() is None:
            sim.kill()
        server.server_close()


def _start_backend(tmp_path, extra_env=None):
    port = _free_port()
    env = dict(os.environ)
    for key in ("MM_API_AUTH_TOKEN", "API_AUTH_TOKEN", "CORS_ORIGINS", "FLASK_DEBUG", "WERKZEUG_RUN_MAIN"):
        env.pop(key, None)
    env.update({
        "MM_ENV": "production", "FLASK_HOST": "127.0.0.1", "FLASK_PORT": str(port), "SECRET_KEY": SECRET,
        "MM_TASK_DB_PATH": str(tmp_path / "tasks.sqlite"), "LLM_API_KEY": env.get("LLM_API_KEY") or "test-key",
        "MM_SHUTDOWN_GRACE": "1", "PYTHONUNBUFFERED": "1",
    })
    env.update(extra_env or {})
    log = open(tmp_path / "server.log", "w")
    proc = subprocess.Popen([sys.executable, os.path.join(BACKEND_DIR, "run.py"), "--prod"], cwd=BACKEND_DIR,
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    return proc, port, log


def test_run_py_exits_promptly_on_sigterm_even_with_an_idle_connection(tmp_path):
    proc, port, log = _start_backend(tmp_path)
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert proc.poll() is None, (tmp_path / "server.log").read_text()
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.3)
        else:
            pytest.fail("backend did not start: " + (tmp_path / "server.log").read_text())

        # A half-sent request keeps a worker thread busy: shutdown must not wait for it forever.
        idle = socket.create_connection(("127.0.0.1", port))
        idle.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n")
        time.sleep(0.3)
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=10)
        elapsed = time.monotonic() - started
        idle.close()
        assert code == 0, (tmp_path / "server.log").read_text()
        assert elapsed < 6, f"took {elapsed:.1f}s to stop"
        assert "Stopped" in (tmp_path / "server.log").read_text()
    finally:
        if proc.poll() is None:
            proc.kill()
        log.close()


# ---------------------------------------------------------------------------
# 2. Production refuses to start open or with placeholders
# ---------------------------------------------------------------------------

def test_production_errors_require_token_cors_and_real_secret(monkeypatch):
    assert Config.production_errors("0.0.0.0") == []          # development: no checks

    monkeypatch.setenv("MM_ENV", "production")
    errs = " ".join(Config.production_errors("0.0.0.0"))
    assert "SECRET_KEY" in errs and "MM_API_AUTH_TOKEN" in errs and "CORS_ORIGINS" in errs

    monkeypatch.setenv("SECRET_KEY", "mirofish-secret-key")
    assert any("default or placeholder" in e for e in Config.production_errors("127.0.0.1"))
    monkeypatch.setenv("SECRET_KEY", "replace-with-output-of-openssl-rand-hex-32")
    assert any("placeholder" in e for e in Config.production_errors("127.0.0.1"))
    monkeypatch.setenv("SECRET_KEY", "short")
    assert any("at least 32" in e for e in Config.production_errors("127.0.0.1"))
    monkeypatch.setenv("SECRET_KEY", SECRET)
    assert Config.production_errors("127.0.0.1") == []        # loopback: token/CORS optional

    monkeypatch.setenv("MM_API_AUTH_TOKEN", "replace-with-output-of-openssl-rand-hex-32")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    errs = Config.production_errors("0.0.0.0")
    assert any("placeholder" in e for e in errs) and any('"*"' in e for e in errs)
    monkeypatch.setenv("CORS_ORIGINS", "https://your-domain.example.com")
    monkeypatch.setenv("MM_API_AUTH_TOKEN", TOKEN)
    assert any("placeholder" in e for e in Config.production_errors("0.0.0.0"))
    monkeypatch.setenv("CORS_ORIGINS", "https://app.acme.io, https://admin.acme.io:8443")
    assert Config.production_errors("0.0.0.0") == []
    monkeypatch.setenv("CORS_ORIGINS", "none")
    assert Config.production_errors("0.0.0.0") == []
    assert all(TOKEN not in e and SECRET not in e for e in Config.production_errors("0.0.0.0"))


def test_create_app_refuses_open_production(monkeypatch):
    _production_env(monkeypatch, host="0.0.0.0")
    with pytest.raises(RuntimeError, match="MM_API_AUTH_TOKEN"):
        create_app()


def test_run_py_refuses_open_production_without_printing_secrets(tmp_path):
    env = dict(os.environ, MM_ENV="production", FLASK_HOST="0.0.0.0", FLASK_PORT=str(_free_port()),
               SECRET_KEY="mirofish-secret-key", MM_TASK_DB_PATH=str(tmp_path / "t.sqlite"),
               LLM_API_KEY=os.environ.get("LLM_API_KEY") or "test-key")
    env.pop("MM_API_AUTH_TOKEN", None)
    env.pop("CORS_ORIGINS", None)
    p = subprocess.run([sys.executable, os.path.join(BACKEND_DIR, "run.py")], cwd=BACKEND_DIR, env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 1
    assert "MM_API_AUTH_TOKEN" in p.stdout and "CORS_ORIGINS" in p.stdout and "SECRET_KEY" in p.stdout
    assert "mirofish-secret-key" not in p.stdout + p.stderr


def test_production_cors_is_closed_unless_listed(monkeypatch):
    _production_env(monkeypatch)
    client = create_app().test_client()
    r = client.get("/api/system/status", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers

    monkeypatch.setenv("CORS_ORIGINS", "https://app.acme.io")
    client = create_app().test_client()
    ok = client.get("/api/system/status", headers={"Origin": "https://app.acme.io"})
    assert ok.headers.get("Access-Control-Allow-Origin") == "https://app.acme.io"
    bad = client.get("/api/system/status", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in bad.headers


def test_config_has_no_hardcoded_secret_default():
    assert Config.SECRET_KEY != "mirofish-secret-key"


# ---------------------------------------------------------------------------
# 3. Rate limiter: X-Forwarded-For spoofing, bounded memory, failed auth
# ---------------------------------------------------------------------------

def test_spoofed_x_forwarded_for_does_not_bypass_rate_limit(monkeypatch):
    monkeypatch.setenv("MM_RATE_LIMIT_RPM", "3")
    client = create_app().test_client()
    codes = [client.get("/api/system/status", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert list(production._RATE_WINDOWS) == ["rpm:127.0.0.1"]


def test_trusted_proxy_uses_forwarded_client_address(monkeypatch):
    monkeypatch.setenv("MM_RATE_LIMIT_RPM", "1")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    client = create_app().test_client()
    # ProxyFix trusts the last hop added by the (single) proxy in front.
    assert client.get("/api/system/status", headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 200
    assert client.get("/api/system/status", headers={"X-Forwarded-For": "203.0.113.6"}).status_code == 200
    assert client.get("/api/system/status", headers={"X-Forwarded-For": "203.0.113.6"}).status_code == 429
    assert set(production._RATE_WINDOWS) == {"rpm:203.0.113.5", "rpm:203.0.113.6"}


def test_rate_limit_memory_is_bounded(monkeypatch):
    monkeypatch.setenv("MM_RATE_LIMIT_MAX_CLIENTS", "50")
    for i in range(500):
        production._check_rate_limit(f"rpm:198.51.100.{i}", 10)
    assert len(production._RATE_WINDOWS) == 50
    # idle keys are swept once their window has passed
    with production._RATE_LOCK:
        for dq in production._RATE_WINDOWS.values():
            dq[-1] = dq[-1] - 120
        production._rate_last_sweep = 0.0
    production._check_rate_limit("rpm:fresh", 10)
    assert list(production._RATE_WINDOWS) == ["rpm:fresh"]


def test_request_counts_are_keyed_by_route_not_raw_path():
    client = create_app().test_client()
    for i in range(30):
        client.get(f"/api/graph/project/proj_{i}")
    keys = [k for k in production._REQUEST_COUNTS if "/api/graph/project/" in k]
    assert not any("proj_" in k for k in keys)
    assert any("<project_id>" in k for k in keys)


def test_failed_auth_attempts_are_rate_limited(monkeypatch):
    monkeypatch.setenv("MM_API_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("MM_AUTH_FAIL_LIMIT", "3")
    client = create_app().test_client()
    good = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/system/status", headers=good).status_code == 200
    codes = [client.get("/api/system/status", headers={"Authorization": f"Bearer wrong{i}"}).status_code for i in range(5)]
    assert codes == [401, 401, 401, 429, 429]
    locked = client.get("/api/system/status", headers=good)
    assert locked.status_code == 429 and locked.headers.get("Retry-After")


# ---------------------------------------------------------------------------
# 4. Probes: public /ready is minimal, details only behind auth, no fake metrics
# ---------------------------------------------------------------------------

def test_public_ready_is_minimal_and_details_need_auth(monkeypatch):
    monkeypatch.setenv("MM_API_AUTH_TOKEN", TOKEN)
    client = create_app().test_client()
    r = client.get("/ready")
    assert r.status_code == 200 and r.get_json() == {"ready": True}
    assert client.get("/api/system/status").status_code == 401
    assert client.get("/metrics").status_code == 401

    status = client.get("/api/system/status", headers={"Authorization": f"Bearer {TOKEN}"}).get_json()["data"]
    text = str(status)
    assert "db_path" not in text and "base_url" not in text and "api.anthropic.com" not in text
    assert status["checks"]["task_store"] == {"ok": True}
    metrics = client.get("/metrics", headers={"X-API-Key": TOKEN}).get_data(as_text=True)
    assert "marketmirror_llm_pool_calls_total" not in metrics
    assert 'marketmirror_tasks_count{status="pending"}' in metrics


def test_ready_reports_503_when_task_store_is_broken(monkeypatch, tmp_path):
    client = create_app().test_client()
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path))   # a directory: sqlite cannot open it
    r = client.get("/ready")
    assert r.status_code == 503 and r.get_json() == {"ready": False}


# ---------------------------------------------------------------------------
# 5. CLI and SDK send the token (env or repo .env) and never print it
# ---------------------------------------------------------------------------

def test_cli_client_sends_token_from_env_and_env_file(monkeypatch, tmp_path):
    from claude_cli import mirofish

    monkeypatch.setenv("MM_API_AUTH_TOKEN", TOKEN)
    c = mirofish.Client("http://127.0.0.1:1")
    assert c.session.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in repr(c)

    monkeypatch.delenv("MM_API_AUTH_TOKEN")
    env_file = tmp_path / ".env"
    env_file.write_text(f"# comment\nLLM_API_KEY=x\nexport MM_API_AUTH_TOKEN=\"{TOKEN}\"\n")
    assert mirofish.api_token(str(env_file)) == TOKEN
    monkeypatch.setattr(mirofish, "REPO_ENV_FILE", str(env_file))
    assert mirofish.Client("http://127.0.0.1:1").session.headers["Authorization"] == f"Bearer {TOKEN}"
    monkeypatch.setattr(mirofish, "REPO_ENV_FILE", str(tmp_path / "missing.env"))
    assert "Authorization" not in mirofish.Client("http://127.0.0.1:1").session.headers


def test_cli_client_authenticates_against_a_live_backend(monkeypatch):
    import run
    from claude_cli import mirofish

    monkeypatch.setenv("MM_API_AUTH_TOKEN", TOKEN)
    app = create_app()
    server = run.BoundedThreadedWSGIServer("127.0.0.1", 0, app, max_threads=4)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert mirofish.Client(base).data("GET", "/api/system/status")["version"] == production.VERSION
        with pytest.raises(mirofish.CLIError) as err:
            mirofish.Client(base, token="wrong-token-value").get("/api/system/status", retries=1)
        assert "HTTP 401" in str(err.value) and TOKEN not in str(err.value) and "wrong-token-value" not in str(err.value)
    finally:
        server.shutdown()
        server.server_close()


def test_sdk_sends_token(monkeypatch, tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(BACKEND_DIR), "sdk"))
    from marketmirror import MarketMirror

    monkeypatch.delenv("MM_API_AUTH_TOKEN", raising=False)
    (tmp_path / ".env").write_text(f"MM_API_AUTH_TOKEN={TOKEN}\n")
    mm = MarketMirror("http://127.0.0.1:1", repo=str(tmp_path))
    assert mm.s.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in repr(mm)
    assert "Authorization" not in MarketMirror("http://127.0.0.1:1", repo=str(tmp_path / "none")).s.headers


# ---------------------------------------------------------------------------
# 7. Task store: no stale foreign cache, restart recovery, cleanup, temp DB
# ---------------------------------------------------------------------------

def _insert_row(db, task_id, status, created=None, task_type="graph_build"):
    created = created or datetime.now()
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO tasks (task_id, task_type, status, created_at, updated_at, progress, message, "
            "result_json, error, metadata_json, progress_detail_json) VALUES (?, ?, ?, ?, ?, ?, '', NULL, NULL, '{}', '{}')",
            (task_id, task_type, status, created.isoformat(), datetime.now().isoformat(), 0),
        )
        conn.commit()
    finally:
        conn.close()


def _set_progress(db, task_id, progress, status="processing"):
    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE tasks SET progress = ?, status = ? WHERE task_id = ?", (progress, status, task_id))
        conn.commit()
    finally:
        conn.close()


def test_tests_use_a_temp_task_db(tmp_path):
    assert TaskManager()._db_path() == str(tmp_path / "tasks.sqlite")


def test_foreign_task_rows_are_read_fresh_not_cached(tmp_path):
    tm = TaskManager()
    tm._init_db()
    db = tm._db_path()
    _insert_row(db, "foreign-1", "processing")          # written by another process
    assert tm.get_task("foreign-1").progress == 0
    _set_progress(db, "foreign-1", 55)
    assert tm.get_task("foreign-1").progress == 55        # not a frozen snapshot
    _set_progress(db, "foreign-1", 100, status="completed")
    assert tm.get_task("foreign-1").status == TaskStatus.COMPLETED
    assert "foreign-1" not in tm._tasks
    listed = {t["task_id"]: t for t in tm.list_tasks()}
    assert listed["foreign-1"]["status"] == "completed"   # list_tasks agrees with get_task


def test_owned_task_updates_and_list_consistency():
    tm = TaskManager()
    tid = tm.create_task("report", metadata={"x": 1})
    tm.update_task(tid, status=TaskStatus.PROCESSING, progress=40)
    assert tm.get_task(tid).progress == 40
    row = tm._load_row(tid)
    assert row.progress == 40 and row.status == TaskStatus.PROCESSING
    assert [t for t in tm.list_tasks("report") if t["task_id"] == tid][0]["progress"] == 40
    assert tm.list_tasks("nothing-of-this-type") == []


def test_restart_marks_interrupted_tasks_failed(tmp_path):
    tm = TaskManager()
    tm._init_db()
    db = tm._db_path()
    _insert_row(db, "left-pending", "pending")
    _insert_row(db, "left-processing", "processing")
    _insert_row(db, "done", "completed")
    owned = tm.create_task("live")                         # a task this process is running
    assert tm.recover_interrupted_tasks() == 2
    for tid in ("left-pending", "left-processing"):
        task = tm.get_task(tid)
        assert task.status == TaskStatus.FAILED and task.error == SERVER_RESTARTED_ERROR
    assert tm.get_task("done").status == TaskStatus.COMPLETED
    assert tm.get_task(owned).status == TaskStatus.PENDING


def test_create_app_runs_restart_recovery():
    tm = TaskManager()
    tm._init_db()
    _insert_row(tm._db_path(), "before-restart", "processing")
    create_app()
    assert tm.get_task("before-restart").error == SERVER_RESTARTED_ERROR


def test_cleanup_old_tasks_deletes_from_db():
    tm = TaskManager()
    tm._init_db()
    db = tm._db_path()
    old = datetime.now() - timedelta(hours=48)
    _insert_row(db, "old-done", "completed", created=old)
    _insert_row(db, "old-running", "processing", created=old)
    _insert_row(db, "new-done", "completed")
    tm.cleanup_old_tasks(max_age_hours=24)
    assert tm.get_task("old-done") is None
    assert tm.get_task("old-running") is not None
    assert tm.get_task("new-done") is not None


def test_schema_is_created_lazily_per_path(monkeypatch, tmp_path):
    tm = TaskManager()
    other = tmp_path / "nested" / "other.sqlite"
    monkeypatch.setenv("MM_TASK_DB_PATH", str(other))
    tid = tm.create_task("x")
    assert other.exists()
    assert tm._load_row(tid).task_type == "x"


def test_db_errors_are_logged_not_swallowed(monkeypatch, tmp_path, caplog):
    import logging
    tm = TaskManager()
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path))   # a directory: cannot be opened
    logging.getLogger("mirofish").propagate = True
    try:
        with caplog.at_level(logging.ERROR, logger="mirofish.tasks"):
            assert tm.get_task("nope") is None
        assert any("task store" in r.getMessage() for r in caplog.records)
    finally:
        logging.getLogger("mirofish").propagate = False


# ---------------------------------------------------------------------------
# 8. Tracebacks never reach clients in production
# ---------------------------------------------------------------------------

def _app_with_failing_route():
    app = create_app()

    @app.route("/api/test/boom")
    def boom():
        try:
            raise ValueError("bad input")
        except ValueError as e:
            import traceback
            return {"success": False, "error": str(e), "traceback": traceback.format_exc(),
                    "data": {"task": {"error": traceback.format_exc()}}}, 500

    return app


def test_tracebacks_kept_in_development():
    body = _app_with_failing_route().test_client().get("/api/test/boom").get_json()
    assert "Traceback (most recent call last)" in body["traceback"]


def test_tracebacks_stripped_in_production(monkeypatch):
    _production_env(monkeypatch)
    r = _app_with_failing_route().test_client().get("/api/test/boom")
    assert r.status_code == 500
    body = r.get_json()
    assert "traceback" not in body
    assert "Traceback" not in r.get_data(as_text=True)
    assert body["error"] == "bad input"
    assert body["data"]["task"]["error"] == "ValueError: bad input"


@pytest.mark.parametrize("env", ["development", "production"])
def test_real_api_error_path_traceback_only_in_development(monkeypatch, env):
    if env == "production":
        _production_env(monkeypatch)
    from app.api import simulation as sim_api

    class Exploding:
        def __init__(self, *a, **k):
            raise RuntimeError("store unavailable")

    monkeypatch.setattr(sim_api, "ZepEntityReader", Exploding)
    monkeypatch.setattr(Config, "memory_backend_configured", classmethod(lambda cls: True))
    r = create_app().test_client().get("/api/simulation/entities/graph_x")
    assert r.status_code == 500
    assert r.get_json()["error"] == "store unavailable"
    assert ("Traceback" in r.get_data(as_text=True)) is (env == "development")


# ---------------------------------------------------------------------------
# 9. X-Request-ID validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("given,kept", [
    ("abc-123_x.y:z", True),
    ("x" * 64, True),
    ("x" * 65, False),
    ("bad id with spaces", False),
    ("evil\r\nSet-Cookie: a=b", False),
    ("<script>", False),
])
def test_request_id_is_validated(given, kept):
    client = create_app().test_client()
    try:
        r = client.get("/health", headers={"X-Request-ID": given})
    except ValueError:      # werkzeug itself refuses header values with newlines
        assert not kept
        return
    rid = r.headers["X-Request-ID"]
    assert (rid == given) is kept
    assert len(rid) <= 64

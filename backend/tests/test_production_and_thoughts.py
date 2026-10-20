"""Tests for Real Agent Cognitive Thought Simulation & Production Deployment Readiness."""

import json
from types import SimpleNamespace
import pytest

from app import create_app
from app.models.task import TaskManager, TaskStatus
from app.services import agent_thoughts as at
from app.services import gtm_suite
from claude_cli import exporter, report_view


class FakeThoughtLLM:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        user = kw["messages"][1]["content"]
        self.calls.append(user)
        body = {
            "thought": "7 days free sounds nice, but if they ask for my debit card upfront I'm closing the tab.",
            "system1_gut": "skeptical",
            "system2_deliberation": "My NPR 1500 monthly discretionary budget is tight and auto-renew is a dealbreaker.",
            "mental_roadblock": "card_trap_fear",
            "private_verdict": "maybe",
            "public_action": "Clicked ad to check if card is required, then left at signup",
            "conviction_0_10": 4.5,
        }
        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=80, completion_tokens=40),
            _mm_provider="gemini",
            _mm_model="gemini-2.5-flash",
        )


def test_production_middleware_auth_ratelimit_probes_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path / "tasks.sqlite"))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    # 1. Public liveness (/health) and readiness (/ready) probes
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.headers.get("X-Request-ID")
    assert r_health.headers.get("X-Content-Type-Options") == "nosniff"

    r_ready = client.get("/ready")
    assert r_ready.status_code == 200
    ready_data = r_ready.get_json()
    assert ready_data["ready"] is True
    assert "upload_folder" in ready_data["checks"]

    # 2. System status and Prometheus /metrics
    r_sys = client.get("/api/system/status")
    assert r_sys.status_code == 200
    assert r_sys.get_json()["data"]["version"] == "2.0.0"

    r_metrics = client.get("/metrics")
    assert r_metrics.status_code == 200
    assert "marketmirror_uptime_seconds" in r_metrics.get_data(as_text=True)
    assert "marketmirror_http_requests_total" in r_metrics.get_data(as_text=True)

    # 3. API Authentication when MM_API_AUTH_TOKEN is configured
    app.config["MM_API_AUTH_TOKEN"] = "prod-secret-token-123"
    assert client.get("/health").status_code == 200  # /health stays open for load balancers
    assert client.get("/ready").status_code == 200   # /ready stays open for k8s probes
    unauth = client.get("/api/system/status")
    assert unauth.status_code == 401
    auth_bearer = client.get("/api/system/status", headers={"Authorization": "Bearer prod-secret-token-123"})
    assert auth_bearer.status_code == 200
    auth_key = client.get("/api/system/status", headers={"X-API-Key": "prod-secret-token-123"})
    assert auth_key.status_code == 200
    app.config.pop("MM_API_AUTH_TOKEN", None)

    # 4. Per-IP Rate Limiting when MM_RATE_LIMIT_RPM is configured
    app.config["MM_RATE_LIMIT_RPM"] = 2
    assert client.get("/api/system/status").status_code == 200
    assert client.get("/api/system/status").status_code == 200
    limited = client.get("/api/system/status")
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")
    app.config.pop("MM_RATE_LIMIT_RPM", None)


def test_sqlite_persistent_task_manager_survives_cache_eviction(tmp_path, monkeypatch):
    db_file = tmp_path / "persistent_tasks.sqlite"
    monkeypatch.setenv("MM_TASK_DB_PATH", str(db_file))
    tm = TaskManager()
    tm._init_db()
    tid = tm.create_task("thought-stream", metadata={"simulation_id": "sim_1"})
    tm.complete_task(tid, {"total_thoughts": 12})

    # Simulate worker restart / cross-worker lookup by clearing in-memory _tasks dict
    with tm._task_lock:
        tm._tasks.pop(tid, None)

    reloaded = tm.get_task(tid)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.COMPLETED
    assert reloaded.result == {"total_thoughts": 12}

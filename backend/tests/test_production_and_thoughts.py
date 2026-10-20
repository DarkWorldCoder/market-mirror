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


def test_agent_thought_simulation_and_harvest(tmp_path):
    people = [
        {
            "agent_id": 1,
            "name": "Asha Rai",
            "age": 21,
            "city": "Kathmandu",
            "country": "Nepal",
            "segment": "Nepal students",
            "occupation": "student",
            "payday_status": "end_of_month_tight",
            "model_provider": "gemini",
            "provenance": {"profile": "real_intake: customer_excerpts"},
            "persona": "Final-year student in Kathmandu who shares an account with her sister.",
            "bde": {
                "background": {"believes": "free trials trap cards", "says_vs_does": "polite yes, strict wallet"},
                "decision_procedure": {"who_they_ask": "sister", "stoppers": ["card upfront"]},
                "evaluation": {"monthly_discretionary": "NPR 1500", "dealbreakers": ["auto-renew"]},
            },
        },
        {
            "agent_id": 2,
            "name": "Bikash Thapa",
            "age": 34,
            "city": "Pokhara",
            "country": "Nepal",
            "segment": "Working parents",
            "occupation": "accountant",
            "model_provider": "claude",
            "persona": "Busy parent in Pokhara.",
            "bde": {},
        },
    ]
    llm = FakeThoughtLLM()
    res = at.run_thought_simulation(
        llm,
        "gemini-2.5-flash",
        {"headline": "Start your 7-day free trial", "text": "15-min home workouts", "price": "NPR 999/mo after trial"},
        people,
    )
    assert res["total_thoughts"] == 2
    assert res["dominant_gut"] == "skeptical"
    assert res["top_roadblock"] == "card_trap_fear"
    assert res["divergence_count"] == 2
    assert set(res["by_provider"].keys()) == {"gemini", "claude"}

    # Save thought_stream.json + simulation_config.json and test harvest_thoughts
    (tmp_path / "simulation_config.json").write_text(json.dumps({"persona_index": people}), encoding="utf-8")
    (tmp_path / "thought_stream.json").write_text(json.dumps(res), encoding="utf-8")
    harvested = at.harvest_thoughts(str(tmp_path))
    assert harvested["total_thoughts"] == 2
    assert harvested["entries"][0]["touchpoint"] == "thought_lab"

    # Dashboard thoughts_section renders the Mindstream section with System 1 / System 2 and Say-vs-Do pills
    bundle = {"config": {"persona_index": people}, "thought_stream": res}
    sec = report_view.thoughts_section(bundle)
    assert sec is not None and sec[0] == "thoughts"
    assert "Private Inner Monologue" in sec[2]
    assert "System 2 BDE Check" in sec[2]
    assert "Say-vs-Do gap" in sec[2]


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


def test_full_gtm_suite_all_five_engines_and_dashboard_render(tmp_path):
    people = [
        {
            "agent_id": i,
            "name": f"Buyer {i}",
            "age": 22 + i,
            "city": "Kathmandu",
            "country": "Nepal",
            "segment": "Nepal students" if i % 2 == 0 else "Working parents",
            "occupation": "student" if i % 2 == 0 else "accountant",
            "payday_status": "end_of_month_tight" if i % 3 == 0 else "mid_month",
            "model_provider": "gemini" if i % 2 == 0 else "claude",
            "bde": {
                "background": {"believes": "free trials trap cards", "says_vs_does": "polite yes, strict wallet", "acquiescence": "high"},
                "decision_procedure": {"who_they_ask": "sister", "stoppers": ["card upfront"]},
                "evaluation": {"monthly_discretionary": "NPR 1800", "discretionary_budget_num": 1800, "dealbreakers": ["card upfront", "auto-renew"]},
            },
        }
        for i in range(1, 13)
    ]
    offer = {"headline": "FitLoop 15-min home routine", "text": "Start your 7-day free trial today", "price": "NPR 999/mo"}
    suite = gtm_suite.run_full_gtm_suite(None, "gemini-2.5-flash", people, offer=offer, run_dir=str(tmp_path))

    # 1. Buying Committee
    bc = suite["buying_committee"]
    assert bc["committee_count"] >= 4
    assert "win_rate_pct" in bc
    assert len(bc["committees"][0]["stakeholders"]) == 4
    assert len(bc["committees"][0]["room_transcript"]) == 4

    # 2. Auto-Iteration Creative Optimizer
    co = suite["creative_optimizer"]
    assert len(co["generations"]) == 3
    assert co["winner"]["ctr_pct"] >= co["baseline"]["ctr_pct"]
    assert co["lift"]["ctr_delta_pts"] >= 0

    # 3. Sales Battlecard & Outbound Sequences
    sb = suite["sales_battlecard"]
    assert len(sb["battlecards"]) >= 2
    assert len(sb["objection_playbook"]) >= 4
    assert len(sb["outbound_sequences"]) >= 1
    assert len(sb["meddpicc"]) == 8

    # 4. 30-Day Longitudinal Customer Journey & Multi-Touch Attribution
    js = suite["journey_simulation"]
    assert len(js["funnel_stages"]) == 7
    assert js["unit_economics"]["ltv"] > 0
    assert js["unit_economics"]["cac"] > 0
    assert len(js["attribution"]) >= 2

    # 5. Pricing & Packaging Conjoint
    pc = suite["pricing_conjoint"]
    assert len(pc["tiers"]) == 5
    assert pc["revenue_maximizing_tier"]
    assert pc["adoption_maximizing_tier"]

    # 6. Competitor Intelligence, Head-to-Head Bake-Off & AI Strategy Suggestions
    ci = suite["competitor_intelligence"]
    assert ci["projected_win_share_after_ai_adds_pct"] >= ci["current_brand_win_share_pct"]
    assert len(ci["competitors"]) >= 3
    assert len(ci["feature_gap_matrix"]) >= 6
    assert len(ci["ai_suggestions"]) >= 5
    assert len(ci["wargame_scenarios"]) >= 3
    assert len(ci["head_to_head_bakeoff"]) >= 10

    # 7. Dashboard sections (#gtm and #competitors) render cleanly
    sec = report_view.gtm_section({"gtm_suite": suite})
    assert sec is not None and sec[0] == "gtm"
    assert "Closed-Loop Creative" in sec[2]
    assert "Pricing &amp; Packaging Conjoint" in sec[2]
    assert "Full-Funnel 30-Day Customer Journey" in sec[2]
    assert "Buying Committee &amp; Household Decision Simulator" in sec[2]
    assert "Sales Battlecard, Objection Matrix" in sec[2]

    c_sec = report_view.competitor_section({"gtm_suite": suite})
    assert c_sec is not None and c_sec[0] == "competitors"
    assert "AI Strategic Suggestions" in c_sec[2]
    assert "Feature Parity &amp; Competitive Whitespace Matrix" in c_sec[2]
    assert "What Each Competitor Has vs. Where They Fail" in c_sec[2]
    assert "Head-to-Head Agent Bake-Off" in c_sec[2]
    assert "Competitive War-Game" in c_sec[2]



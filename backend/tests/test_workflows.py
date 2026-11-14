"""Approved first-run workflows, actual engines and deterministic model responses.

No live credentials or network calls. Each test stores its own projects/tasks.
"""
import copy
import io
import json
import re
from types import SimpleNamespace as NS

import pytest

from app import create_app
from app.config import Config
from app.models.task import TaskManager, TaskStatus
from app.services import workflows as w
from app.services import workflow_engine as engine
from app.utils.model_pool import MultiProviderPool, ProviderSlot


INPUTS = {"name": "Fitloop", "product": "A fifteen-minute home workout app.", "audience": "Busy parents",
          "country": "Nepal", "people": 4, "variants": [{"text": "Workouts that fit your day."},
                                                         {"text": "A fifteen-minute workout at home."}]}


class FakeModel:
    def __init__(self):
        self.calls = []
        self.broken = False
        self.chat = NS(completions=NS(create=self.create))

    def with_options(self, **kwargs):
        assert kwargs["max_retries"] == 0
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][1]["content"]
        if self.broken:
            payload = {"invalid": True}
        elif "Fixed demographics" in prompt:
            count = int(re.search(r"Write (\d+) distinct", prompt)[1])
            payload = {"people": [{"i": i + 1, "name": f"Fictional buyer {i+1}", "occ": "Teacher",
                                    "city": "Kathmandu", "att": "Cautious about recurring fees", "con": ["billing"],
                                    "why": "Clear terms", "bio": "Busy working parent"} for i in range(count)]}
        elif "Grade each answer" in prompt:
            payload = {"grades": [{"i": 0, "grade": "correct"}]}
        elif "first five seconds" in prompt:
            payload = {"what_is_it": "A home workout app", "would_continue": "yes", "read_until": "end",
                       "confusing": "Billing terms", "confusing_type": "price"}
        elif "Simulate how this decision" in prompt:
            payload = {"participants": [{"role": "finance", "stance": "no", "concern": "Billing terms"}],
                       "outcome": "wait", "blocker": "Need billing terms", "what_would_unblock": "Clear pricing"}
        elif "List 8 emails" in prompt:
            payload = {"emails": [{"from": "A fictional sender", "subject": f"Inbox message {i}"} for i in range(8)]}
        else:
            payload = {"p_click": 0.65 if "fifteen-minute workout at home" in prompt else 0.35,
                       "stopped": True, "reaction": "I need to know the commitment.",
                       "objection": "What are the billing terms?", "objection_type": "price",
                       "action": "click", "reason": "The offer is clear", "what_would_make_you_click": "Clear billing"}
        return NS(choices=[NS(message=NS(content=json.dumps(payload)), finish_reason="stop")],
                  model="test-model", usage=NS(prompt_tokens=20, completion_tokens=10))


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake = FakeModel()
    pool = MultiProviderPool([ProviderSlot("openai", "test-model", "https://example.invalid/v1", "test-secret", fake)])
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-secret")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "test-model")
    monkeypatch.setattr(Config, "get_model_pool", classmethod(lambda cls: pool))
    app = create_app()
    app.config.update(TESTING=True)
    monkeypatch.setattr(w, "start_worker", w.run)
    from app.api.setup import SETUP_TOKEN
    c = app.test_client()
    c.environ_base["HTTP_X_SETUP_TOKEN"] = SETUP_TOKEN
    return c, fake, pool


def data(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def new(c, inputs=None):
    return data(c.post("/api/workflows", json={"inputs": inputs or INPUTS}))


def approve(c, record, phase, limit=None, retry=False):
    quote = data(c.post(f"/api/workflows/{record['id']}/estimate", json={"phase": phase}))
    return data(c.post(f"/api/workflows/{record['id']}/approve", json={"phase": phase, "digest": quote["digest"],
                     "call_limit": limit or quote["suggested_call_limit"], "approved": True, "retry": retry}))


def test_full_headline_journey_requires_two_approvals(client):
    c, fake, _ = client
    record = new(c)
    data(c.get("/api/workflows/meta"))
    quote = data(c.post(f"/api/workflows/{record['id']}/estimate", json={"phase": "prepare"}))
    assert not fake.calls and quote["cost_usd"] is None
    assert c.post(f"/api/workflows/{record['id']}/approve", json={"phase": "prepare"}).status_code == 400
    record = approve(c, record, "prepare")
    assert record["stages"]["prepare"]["status"] == "completed"
    assert len(record["people"]) == 4 and len(fake.calls) == 1
    assert "test" not in record["stages"]
    reloaded = data(c.get(f"/api/workflows/{record['id']}"))
    assert reloaded["people"] == record["people"] and len(fake.calls) == 1
    record = approve(c, record, "test")
    assert record["stages"]["test"]["status"] == "completed"
    assert len(fake.calls) == 9
    results = data(c.get(f"/api/workflows/{record['id']}/results"))
    assert results["complete"] and results["variants"][1]["mean"] == .65
    assert results["evidence_type"] == "simulation" and "real" in results["worksheet"]
    assert [r["person"] for r in record["exposures"].values()].count(0) == 2
    assert "test-secret" not in json.dumps(record)
    assert "test-secret" not in c.get(f"/api/workflows/{record['id']}/evidence").text
    assert approve(c, record, "test")["stages"]["test"]["task_id"] == record["stages"]["test"]["task_id"]
    assert len(fake.calls) == 9


def test_call_cap_and_retry_only_remaining_exposures(client):
    c, fake, _ = client
    record = approve(c, new(c), "prepare")
    record = approve(c, record, "test", limit=1)
    assert record["stages"]["test"]["status"] == "failed"
    assert record["stages"]["test"]["calls_used"] == 1
    assert len(record["exposures"]) == 1 and len(fake.calls) == 2
    original = copy.deepcopy(record["exposures"])
    record = approve(c, record, "test", limit=20, retry=True)
    assert len(fake.calls) == 9
    assert record["stages"]["test"]["status"] == "completed"
    for key, value in original.items():
        assert record["exposures"][key] == value


def test_failed_model_answers_are_not_zero_votes(client):
    c, fake, _ = client
    record = approve(c, new(c), "prepare")
    fake.broken = True
    record = approve(c, record, "test")
    result = w.result(record)
    assert record["stages"]["test"]["status"] == "failed"
    assert not result["complete"] and result["verdict"] == "No clear winner"
    assert all(g["mean"] is None and g["answered"] == 0 for g in result["variants"])
    fake.broken = False
    assert approve(c, record, "test", limit=100, retry=True)["stages"]["test"]["status"] == "completed"


def test_changed_inputs_and_provider_invalidate_approval(client):
    c, fake, pool = client
    record = new(c)
    quote = data(c.post(f"/api/workflows/{record['id']}/estimate", json={"phase": "prepare"}))
    changed = {**INPUTS, "country": "India"}
    data(c.put(f"/api/workflows/{record['id']}", json={"inputs": changed}))
    stale = {"phase": "prepare", "digest": quote["digest"], "call_limit": 30, "approved": True}
    assert c.post(f"/api/workflows/{record['id']}/approve", json=stale).status_code == 409
    assert not fake.calls
    record = approve(c, record, "prepare")
    assert c.put(f"/api/workflows/{record['id']}", json={"inputs": INPUTS}).status_code == 409
    revision = data(c.post("/api/workflows", json={"parent_id": record["id"], "inputs": INPUTS}))
    assert revision["revision"] == 2 and not revision["people"] and not revision["stages"]
    pool.slots[0].api_key = "another-account-secret"
    assert c.post(f"/api/workflows/{record['id']}/estimate", json={"phase": "test"}).status_code == 409


def test_interrupted_stage_never_silently_restarts(client, monkeypatch):
    c, fake, _ = client
    monkeypatch.setattr(w, "start_worker", lambda *args: None)
    record = approve(c, new(c), "prepare")
    task = record["stages"]["prepare"]["task_id"]
    TaskManager().fail_task(task, "server restarted")
    record = data(c.get(f"/api/workflows/{record['id']}"))
    assert record["stages"]["prepare"]["status"] == "interrupted"
    assert not fake.calls
    assert approve(c, record, "prepare")["stages"]["prepare"]["task_id"] == task


@pytest.mark.parametrize("change", [{"product": ""}, {"people": True}, {"people": 9999},
                                  {"recipe": "unknown"}, {"ad_budget": -1},
                                  {"variants": [{"text": "Real results, cancel any time"}, {"text": "Try it"}]}])
def test_invalid_or_unsupported_inputs_make_no_calls(client, change):
    c, fake, _ = client
    response = c.post("/api/workflows", json={"inputs": {**INPUTS, **change}})
    if response.status_code == 200:
        wid = response.get_json()["data"]["id"]
        assert c.post(f"/api/workflows/{wid}/estimate", json={"phase": "prepare"}).status_code == 400
    else:
        assert response.status_code == 400
    assert not fake.calls


def test_source_upload_worksheet_and_local_access(client):
    c, fake, _ = client
    text = data(c.post("/api/workflows/source", data={"file": (io.BytesIO(b"Actual billing terms"), "policies.md")}))
    assert text["text"] == "Actual billing terms" and not fake.calls
    assert c.post("/api/workflows/source", json={"url": "http://127.0.0.1:5001/"}).status_code == 400
    record = new(c)
    data(c.put(f"/api/workflows/{record['id']}/worksheet", json={"text": "My real experiment"}))
    assert data(c.get(f"/api/workflows/{record['id']}/results"))["worksheet"] == "My real experiment"
    assert c.get("/api/workflows", environ_overrides={"HTTP_X_SETUP_TOKEN": "wrong"}).status_code == 403
    assert c.get("/api/workflows", environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code == 403
    assert c.post("/api/workflows", json={"inputs": INPUTS}, headers={"Origin": "https://attacker.example"}).status_code == 403


def test_tie_is_inconclusive_and_evidence_is_escaped(client):
    c, _, _ = client
    record = new(c)
    record["exposures"] = {"a": {"variant": "v1", "person": 0, "score": .5}, "b": {"variant": "v2", "person": 0, "score": .5}}
    record["stages"] = {"test": {"status": "completed"}}
    assert w.result(record)["verdict"] == "No clear winner"
    record["inputs"]["product"] = "<script>alert(1)</script>"
    assert "<script>" not in w.evidence_html(record)


def test_local_metrics_only_collect_allowlisted_events(client):
    c, fake, _ = client
    record = new(c)
    data(c.post("/api/workflows/events", json={"name": "setup_connected"}))
    data(c.post("/api/workflows/events", json={"name": "active_seconds", "workflow_id": record["id"], "seconds": 12}))
    assert c.post("/api/workflows/events", json={"name": "product_text", "text": "secret"}).status_code == 400
    metrics = data(c.get("/api/workflows/metrics"))
    assert metrics["drafts"] == 1 and metrics["setup_connected"] == 1 and metrics["active_seconds"] == 12
    assert not fake.calls and "Fitloop" not in json.dumps(metrics)


def test_all_workflow_routes_are_documented(client):
    from app.api.registry import ENDPOINTS
    documented = {(e["method"], e["path"].replace("{wid}", "<wid>")) for e in ENDPOINTS}
    c, _, _ = client
    for rule in c.application.url_map.iter_rules():
        if rule.rule.startswith("/api/workflows"):
            for method in rule.methods - {"OPTIONS", "HEAD"}:
                assert (method, rule.rule) in documented


def test_concurrent_approval_reuses_one_task(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    c, fake, _ = client
    started = []
    monkeypatch.setattr(w, "start_worker", lambda *args: started.append(args))
    record = new(c)
    quote = w.estimate(record["id"], "prepare")
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: w.approve(record["id"], "prepare", quote["digest"], 20), [1, 2]))
    assert len(started) == 1 and not fake.calls
    assert results[0]["stages"]["prepare"]["task_id"] == results[1]["stages"]["prepare"]["task_id"]


def test_missing_provider_allows_drafts_but_no_approval(client, monkeypatch):
    c, fake, _ = client
    monkeypatch.setattr(Config, "LLM_API_KEY", "")
    monkeypatch.setattr(Config, "LLM_POOL", "")
    record = new(c)
    assert data(c.get("/api/workflows/meta"))["provider"]["configured"] is False
    quote = w.estimate(record["id"], "prepare")
    with pytest.raises(w.Conflict):
        w.approve(record["id"], "prepare", quote["digest"], 20)
    assert not fake.calls


@pytest.mark.parametrize("recipe", ["ads", "landing", "saas", "ecommerce", "email", "committee", "regional"])
def test_recipe_runs_existing_engines_without_live_models(client, recipe):
    c, _, _ = client
    record = new(c, {**INPUTS, "recipe": recipe, "facts": "Actual billing terms in this fictional test: 5 USD per month."})
    record = approve(c, record, "prepare")
    record = approve(c, record, "test")
    assert record["stages"]["test"]["status"] == "completed", record["stages"]["test"]
    assert len(record["exposures"]) == 8
    result = w.result(record)
    assert result["complete"] and all(v["mean"] is not None for v in result["variants"])


@pytest.mark.parametrize("recipe", ["landing", "email", "committee"])
def test_recipe_does_not_turn_invalid_answers_into_votes(client, recipe):
    c, fake, _ = client
    record = approve(c, new(c, {**INPUTS, "recipe": recipe}), "prepare")
    fake.broken = True
    record = approve(c, record, "test")
    assert record["stages"]["test"]["status"] == "failed"
    assert not record["exposures"]


def test_blank_worksheet_is_saved_without_replacing_it(client):
    c, _, _ = client
    record = new(c)
    data(c.put(f"/api/workflows/{record['id']}/worksheet", json={"text": ""}))
    assert data(c.get(f"/api/workflows/{record['id']}/results"))["worksheet"] == ""


def test_local_app_bootstraps_without_relaxing_public_or_production_validation(monkeypatch):
    import run
    monkeypatch.setattr(Config, "validate", classmethod(lambda cls: ["model missing"]))
    monkeypatch.setattr(Config, "production_errors", classmethod(lambda cls, host=None: ["production policy"]))
    assert run.startup_errors("127.0.0.1", False, local_app=True) == []
    assert run.startup_errors("0.0.0.0", False, local_app=True) == ["model missing"]
    assert run.startup_errors("127.0.0.1", True, local_app=True) == ["model missing", "production policy"]
    assert run.startup_errors("127.0.0.1", False) == ["model missing"]

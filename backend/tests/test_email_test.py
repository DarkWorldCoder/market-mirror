"""Email test: inputs, spam warnings, the attention gate, a full run with a mocked LLM, metrics and the API."""

import json
import time
from types import SimpleNamespace

from app.services import email_test as et

PEOPLE = [{"agent_id": i, "name": f"P{i}", "persona": "A careful buyer.", "age": 30 + i, "gender": "female" if i % 2 else "male",
           "country": "India" if i < 6 else "Philippines", "segment": "India young professionals" if i < 6 else "Philippines parents",
           "platform_habits": "checks mail on the commute in the morning", "thinking_style": "sceptical"} for i in range(12)]
EMAILS = {"emails": [
    {"id": "a", "from_name": "Fitloop", "subject": "Your 7 days start now", "body": "No card needed. Start today.", "cta": "Start free",
     "send_time": "morning", "sequence": [{"delay_days": 2, "subject": "Day 3: still with us?", "body": "Here is what others did."}]},
    {"id": "b", "from_name": "Fitloop", "subject": "ACT NOW!!! 100% FREE WORKOUTS", "body": "Click here to win", "send_time": "night"}],
    "list_size": 10000, "benchmarks": {"cost_per_send": 0.002, "lead_value": 12}}


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls += 1
        user = kw["messages"][1]["content"]
        if user.startswith("List "):
            body = {"emails": [{"from": "Bank", "subject": "Statement", "kind": "bank"}, {"from": "Boss", "subject": "Report", "kind": "work"},
                               {"from": "Lazada", "subject": "Sale", "kind": "promo"}, {"from": "Nanay", "subject": "Dinner", "kind": "family"}]}
        else:
            click = "Start free" in user and "Day 3" not in user
            body = {"action": "click" if click else "skim", "seconds": 6, "reason": "sige, try ko", "would_buy_now": "maybe" if click else "no",
                    "p_click": 0.6 if click else 0.1, "p_reply": 0.0, "p_unsubscribe": 0.05, "p_spam": 0.0, "what_would_make_you_click": "proof"}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20))


def test_normalize_and_warnings():
    emails, opts = et.normalize_emails(EMAILS)
    assert [e["id"] for e in emails] == ["a", "b"] and opts["list_size"] == 10000
    assert emails[0]["sequence"][0]["step"] == 2 and emails[0]["sequence"][0]["delay_days"] == 2
    w = et.spam_warnings(emails[1])
    assert any("act now" in x for x in w) and any("all caps" in x for x in w) and any("exclamation" in x for x in w)
    assert et.spam_warnings(emails[0]) == []
    try:
        et.normalize_emails([])
        assert False
    except ValueError:
        pass


def test_open_gate_is_deterministic_and_sensible():
    emails, _ = et.normalize_emails(EMAILS)
    tr = {"ad_avoidance": 0.5}
    p_good = et.open_probability(emails[0], PEOPLE[0], tr, 8, 0.2)
    p_spam = et.open_probability(emails[1], PEOPLE[0], tr, 8, 0.2)
    assert 0.05 < p_good < 0.6 and p_spam < p_good                       # spammy night mail opens less
    assert et.open_probability(emails[0], PEOPLE[0], tr, 20, 0.2) < p_good   # crowded inbox
    assert et.open_probability(emails[0], PEOPLE[0], tr, 8, 1.0) > p_good    # known sender
    assert et.open_probability(emails[0], PEOPLE[0], tr, 8, 0.2, step=3) < p_good   # later sequence steps fatigue


def test_run_and_metrics():
    emails, opts = et.normalize_emails(EMAILS)
    client = FakeClient()
    out = et.run_email_test(client, "m", emails, PEOPLE, seed=3, parallel=2, list_size=opts["list_size"], benchmarks=opts["benchmarks"])
    s = out["summary"]
    assert set(out["plan"].values()) == {"a", "b"} and len(out["sessions"]) >= 12
    pa, pb = s["per_email"]["a"], s["per_email"]["b"]
    assert pa["sent"] == 6 and pb["sent"] == 6 and s["ranked"][0] == "a"
    assert pa["open_rate"] is not None and pa["sequence"] and pa["sequence"][0]["step"] == 2
    assert pb["warnings"] and pa["projection"]["list_size"] == 10000 and "cpl" in pa["projection"] or pa["projection"]["leads"] == 0
    assert out["usage"]["calls"] == client.calls and client.calls >= 2
    assert s["subject_lines"][0]["subject"] == "Your 7 days start now"
    assert all(r.get("p_open") is not None for r in out["sessions"])


def test_email_api(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.services.simulation_manager import SimulationManager
    from app.api import market
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    sim = tmp_path / "sim_e"
    sim.mkdir()
    (sim / "state.json").write_text(json.dumps({"simulation_id": "sim_e", "project_id": "p", "graph_id": "g", "status": "ready"}))
    monkeypatch.setattr(market, "_people", lambda sid: (PEOPLE, {}))
    monkeypatch.setattr(market, "_client", lambda: FakeClient())
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/email-test", json={"simulation_id": "sim_e", "emails": []}).status_code == 400
    r = c.post("/api/simulation/email-test", json={"simulation_id": "sim_e", "emails": EMAILS})
    assert r.status_code == 200 and r.get_json()["data"]["emails"] == 2
    task_id = r.get_json()["data"]["task_id"]
    for _ in range(200):
        st = c.post("/api/simulation/market-task/status", json={"task_id": task_id}).get_json()["data"]
        if st["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert st["status"] == "completed", st
    got = c.get("/api/simulation/sim_e/email-test").get_json()["data"]
    assert got["summary"]["ranked"] and got["list_size"] == 10000

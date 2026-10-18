"""Events API (brand posts + scheduled events) and the captions endpoint, with a mocked LLM."""

import json
import os
from types import SimpleNamespace

import pytest

from app import create_app
from app.config import Config
from app.services.simulation_manager import SimulationManager

CFG = {"persona_index": [{"agent_id": 0, "name": "Acme", "kind": "graph"},
                         {"agent_id": 1, "name": "Priya Menon", "kind": "persona"}],
       "event_config": {"initial_posts": [], "scheduled_events": [], "hot_topics": []}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    sim = tmp_path / "sim_x"
    sim.mkdir()
    (sim / "state.json").write_text(json.dumps({"simulation_id": "sim_x", "project_id": "p", "graph_id": "g",
                                                "status": "ready"}), encoding="utf-8")
    (sim / "simulation_config.json").write_text(json.dumps(CFG), encoding="utf-8")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client(), sim


def test_put_events_writes_config_and_get_reads_it(client):
    c, sim = client
    r = c.put("/api/simulation/sim_x/events", json={"posts": [{"agent": "Acme", "content": "Hello world"}],
                                                   "events": [{"round": 2, "agent": "acme", "content": "Launch", "label": "launch"}]})
    assert r.status_code == 200, r.get_json()
    cfg = json.loads((sim / "simulation_config.json").read_text(encoding="utf-8"))
    assert cfg["event_config"]["initial_posts"] == [{"poster_agent_id": 0, "content": "Hello world", "platform": "both",
                                                     "poster_type": "brand"}]
    assert cfg["event_config"]["scheduled_events"][0]["round"] == 2
    g = c.get("/api/simulation/sim_x/events").get_json()["data"]
    assert g["scheduled_events"][0]["label"] == "launch"
    bad = c.put("/api/simulation/sim_x/events", json={"events": [{"round": 0, "agent": 0, "content": "x"}]})
    assert bad.status_code == 400
    assert c.put("/api/simulation/nope/events", json={}).status_code == 404


def test_put_events_refused_while_running(client):
    c, sim = client
    (sim / "run_state.json").write_text(json.dumps({"runner_status": "running"}), encoding="utf-8")
    r = c.put("/api/simulation/sim_x/events", json={"posts": [{"agent": 0, "content": "x"}]})
    assert r.status_code == 409


def test_captions_endpoint(client, monkeypatch):
    c, _ = client
    from app.api import market

    def fake_client():
        def create(**kw):
            assert "instagram" in kw["messages"][1]["content"]
            body = {"captions": [{"angle": "price", "hook": "Cheaper than chai", "body": "15-min workouts.\nTry free.",
                                  "hashtags": ["#fit", "homeworkout"], "cta": "Start free trial", "format": "reel",
                                  "media": "phone screen", "why": "price anchor"}]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)), finish_reason="stop")])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(market, "_client", fake_client)
    r = c.post("/api/simulation/captions", json={"brief": "Fitloop app", "platform": "instagram", "n": 3,
                                                 "objections": ["card required"]})
    assert r.status_code == 200, r.get_json()
    cap = r.get_json()["data"]["captions"][0]
    assert cap["id"] == "in_1" and cap["text"].startswith("Cheaper than chai\n15-min")
    assert cap["hashtags"] == ["fit", "homeworkout"] and cap["format"] == "reel"
    assert c.post("/api/simulation/captions", json={}).status_code == 400

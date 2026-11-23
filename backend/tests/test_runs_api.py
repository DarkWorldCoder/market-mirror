"""Workspace runs API: token and loopback guard, listing, detail, file reads and path checks."""

import json

import pytest

from app import create_app
from app.api import setup as setup_api


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    (root / "acme").mkdir(parents=True)
    (root / "acme" / "run_manifest.json").write_text(json.dumps({"title": "Acme test", "simulation_id": "sim_1",
                                                                  "finished_at": "2026-11-23T10:00:00"}))
    (root / "acme" / "summary.json").write_text(json.dumps({"decision": {"decision": "iterate", "summary": "Fix price"},
                                                             "marketing": {"people": 40}}))
    (root / "acme" / "disclosure.md").write_text("# How this was made")
    (root / "acme" / "dashboard.html").write_text("<html>dash</html>")
    (root / "acme" / "secret.env").write_text("KEY=1")
    (root / "_preview").mkdir()
    (root / "_preview" / "summary.json").write_text("{}")
    (root / "empty").mkdir()
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(root))
    monkeypatch.setattr(setup_api, "SETUP_TOKEN", "tok")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


H = {"X-Setup-Token": "tok"}


def test_needs_the_setup_token(client):
    assert client.get("/api/runs").status_code == 403
    assert client.get("/api/runs", headers={"X-Setup-Token": "nope"}).status_code == 403


def test_lists_runs_with_their_cards(client):
    runs = client.get("/api/runs", headers=H).get_json()["data"]["runs"]
    assert [r["name"] for r in runs] == ["acme"]               # folders starting with _ and empty ones are skipped
    r = runs[0]
    assert (r["title"], r["decision"], r["people"], r["simulation_id"], r["has_dashboard"]) == \
        ("Acme test", "iterate", 40, "sim_1", True)


def test_detail_and_files(client):
    d = client.get("/api/runs/acme", headers=H).get_json()["data"]
    assert d["files"] == ["dashboard.html", "disclosure.md", "run_manifest.json", "summary.json"]
    assert client.get("/api/runs/acme/files/summary.json", headers=H).get_json()["data"]["marketing"]["people"] == 40
    md = client.get("/api/runs/acme/files/disclosure.md", headers=H)
    assert md.status_code == 200 and b"How this was made" in md.data
    html = client.get("/api/runs/acme/files/dashboard.html", headers=H)
    assert "sandbox" in html.headers["Content-Security-Policy"]
    dl = client.get("/api/runs/acme/files/disclosure.md?download=1", headers=H)
    assert "attachment" in dl.headers.get("Content-Disposition", "")


@pytest.mark.parametrize("path", ["/api/runs/..", "/api/runs/missing", "/api/runs/acme/files/secret.env",
                                  "/api/runs/acme/files/..%2Fsummary.json", "/api/runs/acme/files/nope.json",
                                  "/api/runs/_preview/files/summary.json"])
def test_refuses_unknown_or_unsafe_paths(client, path):
    assert client.get(path, headers=H).status_code in (404, 403)


def test_thoughts_harvest_the_run_folder(client, tmp_path):
    run = tmp_path / "runs" / "acme"
    (run / "survey.json").write_text(json.dumps({"offer": "Acme", "responses": [
        {"agent_id": 3, "name": "Ana", "answer": {"main_objection": "Too dear for me", "would_convert": "no"}}]}))
    (run / "feed_test.json").write_text(json.dumps({"sessions": [
        {"agent_id": 3, "name": "Ana", "platform": "twitter", "creative_id": "a1", "ad": {"thought": "Looks fun", "click": True}}]}))
    assert client.get("/api/runs/acme/thoughts").status_code == 403
    d = client.get("/api/runs/acme/thoughts", headers=H).get_json()["data"]
    texts = {(e["source"], e["text"], e["did"]) for e in d["entries"]}
    assert ("survey", "Too dear for me", "would no take it") in texts
    assert ("ad in feed", "Looks fun", "clicked") in texts
    assert d["people"] == 1


def test_status_from_saved_files(client, tmp_path):
    run = tmp_path / "runs" / "acme"
    (run / "run_status.json").write_text(json.dumps({"runner_status": "completed", "current_round": 3, "total_rounds": 3}))
    (run / "timeline.json").write_text(json.dumps([{"round_num": 1, "total_actions": 9, "twitter_actions": 4,
                                                    "reddit_actions": 5, "active_agents_count": 6}]))
    d = client.get("/api/runs/acme/status", headers=H).get_json()["data"]
    assert d["live"] is False and d["run"]["runner_status"] == "completed"
    assert d["rounds"] == [{"round": 1, "actions": 9, "twitter": 4, "reddit": 5, "active": 6}]
    assert [s["id"] for s in d["stages"]] == ["graph", "people", "report"]
    assert [s["done"] for s in d["stages"]] == [False, True, False]
    assert client.get("/api/runs/acme", headers=H).get_json()["data"]["simulation_on_backend"] is False
    assert client.get("/api/runs/../status", headers=H).status_code in (403, 404)

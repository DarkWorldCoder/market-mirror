"""Chat agent endpoints: SSE framing, live audience estimates, the tool list. Fake turn, no model calls."""
import json

import pytest

from app import create_app
from app.api import setup
from app.services.chat_agent import loop

H = {"X-Setup-Token": "agent-test"}
BODY = {"session_id": "chat-api-0001", "messages": [{"role": "user", "content": "test two headlines"}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(setup, "SETUP_TOKEN", "agent-test")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def frames(response):
    out = []
    for block in response.get_data(as_text=True).strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) >= 2 and lines[0].startswith("event: "):
            out.append((lines[0][7:], json.loads(lines[1][6:])))
    return out


def test_stream_frames_every_agent_event_and_ends_on_done(client, monkeypatch):
    def fake(value, emit, disconnected):
        emit("plan", {"phase": "test"})
        emit("tool_start", {"id": "1", "tool": "list_runs"})
        emit("tool_progress", {"id": "1", "log_tail": ["a"]})
        emit("tool_result", {"id": "1", "status": "completed"})
        emit("artifact", {"kind": "compare", "compare": {"a": "x", "b": "y"}})
        emit("approval_request", {"id": "ap_1", "kind": "spend"})
        emit("private_reasoning", {"secret": "DO_NOT_STREAM"})
        emit("done", {"status": "waiting"})
    monkeypatch.setattr(loop, "run_turn", fake)
    response = client.post("/api/workspace/agent/stream", json=BODY, headers=H)
    names = [n for n, _ in frames(response)]
    assert names == ["plan", "tool_start", "tool_progress", "tool_result", "artifact", "approval_request", "done"]
    assert "DO_NOT_STREAM" not in response.get_data(as_text=True)
    assert response.headers["Content-Type"].startswith("text/event-stream")


def test_stream_errors_carry_status_and_actions(client, monkeypatch):
    def fake(value, emit, disconnected):
        raise loop.AgentError("Your Claude key was rejected. Nothing was spent.", 401, "auth", [{"id": "open_model_settings", "label": "Open model settings"}])
    monkeypatch.setattr(loop, "run_turn", fake)
    got = frames(client.post("/api/workspace/agent/stream", json=BODY, headers=H))
    assert got == [("error", {"message": "Your Claude key was rejected. Nothing was spent.", "status": 401, "code": "auth",
                              "actions": [{"id": "open_model_settings", "label": "Open model settings"}]})]


def test_stream_rejects_bad_requests_and_needs_the_token(client):
    assert client.post("/api/workspace/agent/stream", json={"messages": []}, headers=H).status_code == 400
    assert client.post("/api/workspace/agent/stream", json=BODY).status_code in (401, 403)


def test_audience_estimate_is_live_and_flags_fit(client, monkeypatch):
    from app.services.chat_agent import bridge
    monkeypatch.setattr(bridge.Executor, "spend_plan", lambda self, name, args: {"people": 14, "total_calls": 40, "usd_estimate": 0.2})
    body = {"segments": [{"label": "Parents", "count": 8, "country": "India"}, {"label": "Dads", "count": 6, "country": "Kenya"}]}
    data = client.post("/api/workspace/agent/audience/estimate", json=body, headers=H).get_json()["data"]
    assert data["people"] == 14 and data["estimate"]["usd_estimate"] == 0.2
    assert {w["code"] for w in data["fit_check"]["warnings"]} >= {"small_segments", "less_covered_markets"}
    bad = client.post("/api/workspace/agent/audience/estimate", json={"segments": [{"count": 3}]}, headers=H)
    assert bad.status_code == 400


def test_tool_list_shows_cost_classes(client):
    rows = {r["name"]: r for r in client.get("/api/workspace/agent/tools", headers=H).get_json()["data"]["tools"]}
    assert rows["market_test"]["cost"] == "spend" and rows["compare_runs"]["cost"] == "free"
    assert rows["research"]["cost"] == "outside" and rows["open_view"]["source"] == "app"


def test_job_ids_are_validated(client):
    assert client.get("/api/workspace/agent/jobs/../../etc", headers=H).status_code == 404
    assert client.get("/api/workspace/agent/jobs/notahexid!", headers=H).status_code == 404

"""Provider settings page: local-only, token-guarded, keys stored masked, provider applied to the running backend."""

import json
import os

import pytest

from app import create_app
from app.api import setup as st
from app.config import Config

LOCAL = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "ROOT", tmp_path)
    monkeypatch.setattr(st, "LOGS", tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_API_KEY", "LLM_GATEWAY", "LLM_POOL"):
        monkeypatch.setattr(Config, k, getattr(Config, k, None)) if hasattr(Config, k) else None
    saved = dict(os.environ)
    app = create_app()
    yield app.test_client()
    os.environ.clear()
    os.environ.update(saved)


def H(token=None, origin=None):
    h = {"X-Setup-Token": st.SETUP_TOKEN if token is None else token}
    if origin:
        h["Origin"] = origin
    return h


def test_only_this_computer_with_the_token(client):
    assert client.get("/setup", environ_base={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403
    assert client.get("/setup", environ_base=LOCAL).status_code == 200
    assert client.get("/api/setup/state", environ_base=LOCAL).status_code == 403
    assert client.get("/api/setup/state", headers=H("wrong"), environ_base=LOCAL).status_code == 403
    assert client.get("/api/setup/state", headers=H(), environ_base={"REMOTE_ADDR": "10.1.1.1"}).status_code == 403
    r = client.post("/api/setup/key", json={"name": "OPENAI_API_KEY", "value": "sk-" + "a" * 30},
                    headers=H(origin="https://evil.example"), environ_base=LOCAL)
    assert r.status_code == 403


def test_key_is_stored_owner_only_and_never_returned(client, tmp_path):
    key = "sk-test-" + "b" * 30
    r = client.post("/api/setup/key", json={"name": "OPENAI_API_KEY", "value": key}, headers=H(), environ_base=LOCAL)
    assert r.status_code == 200 and key not in r.get_data(as_text=True)
    env = tmp_path / ".env"
    assert json.loads(env.read_text().split("OPENAI_API_KEY=")[1].splitlines()[0]) == key
    assert oct(env.stat().st_mode)[-3:] == "600"
    state = client.get("/api/setup/state", headers=H(), environ_base=LOCAL)
    assert key not in state.get_data(as_text=True) and state.get_json()["data"]["keys"]["OPENAI_API_KEY"].endswith("bbbb")
    assert client.post("/api/setup/key", json={"name": "PATH", "value": "x" * 20}, headers=H(), environ_base=LOCAL).status_code == 400
    assert client.post("/api/setup/key", json={"name": "OPENAI_API_KEY", "value": "has space " * 3}, headers=H(), environ_base=LOCAL).status_code == 400


def test_api_provider_is_applied_to_the_running_backend(client, tmp_path):
    client.post("/api/setup/key", json={"name": "GEMINI_API_KEY", "value": "AIza" + "c" * 30}, headers=H(), environ_base=LOCAL)
    r = client.post("/api/setup/provider", json={"kind": "api", "provider": "gemini", "model": "gemini-3.8-flash"},
                    headers=H(), environ_base=LOCAL)
    assert r.status_code == 200, r.get_json()
    assert Config.LLM_PROVIDER == "gemini" and Config.LLM_MODEL_NAME == "gemini-3.8-flash"
    assert "generativelanguage" in Config.LLM_BASE_URL
    bad = client.post("/api/setup/provider", json={"kind": "login", "backend": "nope"}, headers=H(), environ_base=LOCAL)
    assert bad.status_code == 400


def test_gateway_port_conflict_and_missing_cli(client, monkeypatch):
    monkeypatch.setattr(st, "_health", lambda port: {"backend": "claude"} if port == 5055 else None)
    r = client.post("/api/setup/gateway", json={"action": "start", "backend": "codex", "port": 5055}, headers=H(), environ_base=LOCAL)
    assert r.status_code == 400 and "already used" in r.get_json()["error"]
    monkeypatch.setattr(st, "_find_bin", lambda b: None)
    r = client.post("/api/setup/gateway", json={"action": "start", "backend": "codex", "port": 5099}, headers=H(), environ_base=LOCAL)
    assert r.status_code == 400 and "not installed" in r.get_json()["error"]

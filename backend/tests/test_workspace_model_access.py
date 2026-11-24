"""Chat models work locally without fuss and stay locked down in production.

No real CLI, gateway, network or model call: start_gateway, health checks and catalogs are mocked.
"""
import json
import logging
from types import SimpleNamespace as NS

import pytest

from app.config import Config
from app.api import setup
from app.services import workspace_chat as chat, workspace_local_models as local, workspace_settings as settings

KEY = "sk-ant-STALE-KEY-NEVER-SHOWN"
REAL_DISCOVER, REAL_CACHED = local.discover, local.cached_local_models


class HTTPError(Exception):
    def __init__(self, status):
        super().__init__(f"provider said no for {KEY}")
        self.status_code = status


class APIConnectionError(Exception):
    pass


class APITimeoutError(Exception):
    pass


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("MM_WORKER_SECRET", raising=False)
    monkeypatch.delenv("MM_ENV", raising=False)
    monkeypatch.setattr(setup, "LOGS", tmp_path)
    monkeypatch.setattr(setup, "_find_bin", lambda backend: None)
    monkeypatch.setattr(setup, "start_gateway", lambda *a, **k: pytest.fail("no gateway start expected"))
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[]))
    monkeypatch.setattr(chat, "_gateway_health", lambda port: None)
    monkeypatch.setattr(chat, "_gateway_models", lambda port, key: None)
    monkeypatch.setattr(local, "cached_local_models", lambda: [])
    chat.clear_rejections()
    yield tmp_path
    chat.clear_rejections()


def anthropic_slot():
    return NS(provider="claude", model="claude-haiku-4-5", base_url="https://api.anthropic.com/v1/", api_key=KEY)


def running_claude(monkeypatch):
    (setup.LOGS / "gateway-5055.token").write_text("GATEWAY-TOKEN")
    monkeypatch.setattr(chat, "_gateway_health", lambda port: {"backend": "claude", "model": "sonnet", "available": True,
                                                              "auth_required": True} if port == 5055 else None)
    monkeypatch.setattr(chat, "_gateway_models", lambda port, key: ["sonnet"] if port == 5055 and key == "GATEWAY-TOKEN" else None)


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.client = self

    def with_options(self, **kwargs):
        return self


# ---------------------------------------------------------------- (a) error mapping

@pytest.mark.parametrize("error,status,words", [
    (HTTPError(401), 502, "Your Anthropic key was rejected. Update it in Model settings or use your Claude Code login instead."),
    (HTTPError(403), 502, "Your Anthropic key was rejected."),
    (HTTPError(429), 429, "Anthropic is rate limiting requests right now"),
    (APIConnectionError("connect refused"), 503, "Anthropic is not reachable"),
    (APITimeoutError("timed out"), 503, "Anthropic is not reachable"),
    (ConnectionRefusedError(111, "refused"), 503, "Anthropic is not reachable"),
    (HTTPError(529), 502, "Anthropic had a problem answering (HTTP 529)"),
    (RuntimeError("odd"), 502, "Your model could not answer this message"),
])
def test_provider_errors_map_to_clear_messages(isolated, error, status, words):
    mapped = chat.provider_error(error, {"label": "Anthropic", "gateway": False, "rejection": None})
    assert mapped.status == status
    assert words in str(mapped)
    assert KEY not in str(mapped)


def test_wrapped_status_and_gateway_wording(isolated):
    outer = RuntimeError("wrapper")
    outer.__cause__ = HTTPError(401)
    assert "Anthropic key was rejected" in str(chat.provider_error(outer, {"label": "Anthropic"}))
    gateway = chat.provider_error(HTTPError(401), {"label": "Claude Code login", "gateway": True})
    assert str(gateway).startswith("Your Claude Code login was rejected")
    local_server = chat.provider_error(APIConnectionError(), {"label": "Ollama"})
    assert str(local_server).startswith("Ollama is not reachable")
    assert str(chat.provider_error(APIConnectionError(), None)).startswith("The model provider is not reachable")


def test_failure_logs_the_class_never_the_key(isolated):
    lines = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())
    handler = Collect()
    chat.logger.addHandler(handler)
    try:
        chat.provider_error(HTTPError(401), {"label": "Anthropic"})
    finally:
        chat.logger.removeHandler(handler)
    text = "\n".join(lines)
    assert "HTTPError" in text and "401" in text
    assert KEY not in text


def test_rejected_key_marks_route_and_claude_login_becomes_default(isolated, monkeypatch):
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[anthropic_slot()]))
    running_claude(monkeypatch)
    monkeypatch.setattr(chat, "LLMClient", FakeClient)
    data = chat.models()
    api = next(row for row in data["models"] if row["model"] == "claude-haiku-4-5")
    assert data["default_id"] == api["id"] and api["status"] == "configured"
    client = chat._model(api["id"])
    assert KEY not in json.dumps(client._mm_route)
    chat.provider_error(HTTPError(401), client._mm_route)
    data = chat.models()
    api = next(row for row in data["models"] if row["model"] == "claude-haiku-4-5")
    login = next(row for row in data["models"] if row["model"] == "sonnet" and row.get("connection_backend") == "claude")
    assert api["status"] == "key_rejected" and api["available"] is False
    assert login["status"] == "connected"
    assert data["default_id"] == login["id"]
    assert KEY not in json.dumps(data)
    with pytest.raises(chat.ChatError, match="key was rejected"):
        chat._model(api["id"])
    # A new key is a new fingerprint: the mark no longer applies.
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[NS(**{**vars(anthropic_slot()), "api_key": "sk-ant-NEW"})]))
    assert next(row for row in chat.models()["models"] if row["model"] == "claude-haiku-4-5")["status"] == "configured"


def test_chat_endpoint_returns_mapped_message(isolated, monkeypatch, tmp_path):
    from app import create_app
    monkeypatch.setattr(setup, "SETUP_TOKEN", "tok")
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(tmp_path / "runs"))

    class Failing:
        _mm_route = {"label": "Anthropic", "gateway": False, "rejection": ("x", "y")}

        def chat_json(self, *a, **k):
            raise HTTPError(401)
    monkeypatch.setattr(chat, "_model", lambda *a: Failing())
    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/workspace/chat", headers={"X-Setup-Token": "tok"},
                                      json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 502
    assert response.json["error"].startswith("Your Anthropic key was rejected")
    assert KEY not in response.get_data(as_text=True)


# ---------------------------------------------------------------- (b) auto-connect

def test_installed_login_connects_on_first_use(isolated, monkeypatch):
    monkeypatch.setattr(setup, "_find_bin", lambda backend: "/bin/claude" if backend == "claude" else None)
    monkeypatch.setattr(chat, "LLMClient", FakeClient)
    started, events = [], []

    def start(backend, port, model="", workers=8):
        started.append((backend, port, model))
        running_claude(monkeypatch)
        return {"port": port, "started": True, "backend": backend}
    monkeypatch.setattr(setup, "start_gateway", start)
    data = chat.models()
    haiku = next(row for row in data["models"] if row["model"] == "haiku")
    assert haiku["status"] == "connect_on_first_use" and haiku["available"] is True
    token = chat._EVENTS.set(events.append)
    try:
        client = chat._model(haiku["id"])
    finally:
        chat._EVENTS.reset(token)
    assert started == [("claude", 5055, "haiku")]
    assert client.kwargs == {"api_key": "GATEWAY-TOKEN", "base_url": "http://127.0.0.1:5055/v1", "model": "haiku"}
    assert [e["status"] for e in events] == ["working", "completed"]
    assert all("GATEWAY-TOKEN" not in json.dumps(e) for e in events)


def test_saved_gateway_slot_that_is_down_restarts_its_login(isolated, monkeypatch):
    (setup.LOGS / "gateway-5055.token").write_text("GATEWAY-TOKEN")
    slot = NS(provider="openai", model="sonnet", base_url="http://127.0.0.1:5055/v1", api_key="GATEWAY-TOKEN")
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[slot]))
    monkeypatch.setattr(setup, "_find_bin", lambda backend: "/bin/claude" if backend == "claude" else None)
    monkeypatch.setattr(chat, "LLMClient", FakeClient)
    started = []
    monkeypatch.setattr(setup, "start_gateway", lambda backend, port, model="", workers=8: (started.append(backend), running_claude(monkeypatch)))
    data = chat.models()
    first = data["models"][0]
    assert first["status"] == "connect_on_first_use" and first["connection_backend"] == "claude"
    assert chat._model().kwargs["model"] == "sonnet"
    assert started == ["claude"]


def test_failed_start_and_signed_out_login_explain_what_to_do(isolated, monkeypatch):
    monkeypatch.setattr(setup, "_find_bin", lambda backend: "/bin/claude" if backend == "claude" else None)
    def broken(*a, **k):
        raise RuntimeError("the gateway did not start: boom")
    monkeypatch.setattr(setup, "start_gateway", broken)
    sonnet = next(row for row in chat.models()["models"] if row["model"] == "sonnet")
    with pytest.raises(chat.ChatError, match="Could not connect your Claude Code login") as error:
        chat._model(sonnet["id"])
    assert error.value.status == 409
    # Started, but the login has no usable models: the person is told to sign in.
    monkeypatch.setattr(setup, "start_gateway", lambda *a, **k: monkeypatch.setattr(
        chat, "_gateway_health", lambda port: {"backend": "claude", "available": False, "auth_required": True} if port == 5055 else None))
    with pytest.raises(chat.ChatError, match="not signed in"):
        chat._model(sonnet["id"])


def test_not_installed_cli_is_never_started(isolated, monkeypatch):
    slot = NS(provider="claude", model="sonnet", base_url="http://127.0.0.1:5055/v1", api_key="tok")
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[slot]))
    row = chat.models()["models"][0]
    assert row["available"] is False and row["status"] == "needs_connection"
    with pytest.raises(chat.ChatError, match="unavailable"):
        chat._model(row["id"])


def test_unknown_local_server_model_triggers_one_rediscovery(isolated, monkeypatch):
    found = []
    monkeypatch.setattr(local, "discover", lambda refresh=False: found.append(refresh))
    with pytest.raises(ValueError):
        chat._model("m_" + "1" * 24)
    assert found == [True]


# ---------------------------------------------------------------- (c) production

def test_production_lists_only_configured_remote_models(isolated, monkeypatch):
    monkeypatch.setenv("MM_ENV", "production")
    slots = [anthropic_slot(), NS(provider="openai", model="sonnet", base_url="http://127.0.0.1:5055/v1", api_key="t"),
             NS(provider="ollama", model="llama3", base_url="http://127.0.0.1:11434/v1", api_key="local")]
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=slots))
    monkeypatch.setattr(setup, "_find_bin", lambda *a: "/bin/claude")
    monkeypatch.setattr(chat, "_gateway_health", lambda *a: pytest.fail("production must not probe local gateways"))
    monkeypatch.setattr(local, "cached_local_models", lambda: pytest.fail("production must not list local models"))
    monkeypatch.setattr(local, "discover", lambda *a, **k: pytest.fail("production must not scan local servers"))
    data = chat.models()
    assert [row["model"] for row in data["models"]] == ["claude-haiku-4-5"]
    assert data["production"] is True and data["local_app"] is False
    with pytest.raises(ValueError):
        chat._model("m_" + "2" * 24)


def test_production_never_auto_connects(isolated, monkeypatch):
    monkeypatch.setattr(setup, "_find_bin", lambda backend: "/bin/claude")
    entry = {"public": {"id": "m_x", "connection_backend": "claude", "status": "connect_on_first_use"},
             "base_url": "http://127.0.0.1:5055/v1", "model": "sonnet"}
    monkeypatch.setenv("MM_ENV", "production")
    with pytest.raises(chat.ChatError, match="unavailable"):
        chat._connect(entry)


def test_production_local_discovery_and_settings_are_locked(isolated, monkeypatch):
    monkeypatch.setenv("MM_ENV", "production")
    monkeypatch.setattr(local, "_get", lambda *a, **k: pytest.fail("production must not read local servers"))
    assert REAL_DISCOVER(refresh=True)["models"] == []
    assert REAL_CACHED() == []
    state = settings._llm_state()
    assert state["locked"] is True
    assert all(row["id"] not in {"ollama", "lmstudio"} for row in state["providers"])
    with pytest.raises(ValueError, match="sets its models"):
        settings._llm_values({"provider": "openai", "api_key": "sk-new"})


def test_local_settings_are_not_locked(isolated):
    assert settings._llm_state()["locked"] is False

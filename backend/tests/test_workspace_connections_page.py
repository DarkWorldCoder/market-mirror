"""Connections page endpoints: MCP setup snippets, checking a server before saving, and a free key check.

No external accounts, models or MCP servers are contacted: every transport is replaced in the test.
"""
import json

import pytest

from app import create_app
from app.api import setup
from app.config import Config
from app.services import workspace_connectors as mcp
from app.services import workspace_settings
from app.utils.model_pool import PROVIDER_DEFAULTS

H = {"X-Setup-Token": "connections-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(setup, "SETUP_TOKEN", "connections-test")
    monkeypatch.delenv("MM_ENV", raising=False)
    monkeypatch.delenv("MM_WORKER_SECRET", raising=False)
    monkeypatch.delenv("LLM_GATEWAY", raising=False)
    for field in ("LLM_PROVIDER", "LLM_MODEL_NAME", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.setattr(Config, field, getattr(Config, field))
    for name, spec in PROVIDER_DEFAULTS.items():
        for key in (spec.get("key_env"), *spec.get("alt_key_envs", ()), f"{name.upper()}_BASE_URL"):
            if key:
                monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(Config, "LLM_API_KEY", "")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


# ---------------------------------------------------------------- MarketMirror's own MCP server, for other apps

def test_mcp_setup_needs_the_setup_token(client):
    assert client.get("/api/workspace/mcp-setup").status_code == 403


def test_mcp_setup_uses_real_paths_and_no_secrets(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret-value-1234567890")
    data = client.get("/api/workspace/mcp-setup", headers=H).json["data"]
    server = setup.ROOT / "plugin" / "skills" / "market-mirror" / "scripts" / "mcp_server.py"
    assert data["server_path"] == str(server)
    assert data["server_found"] is True
    assert data["home"] == str(setup.ROOT)
    ids = [c["id"] for c in data["clients"]]
    assert ids == ["claude-desktop", "claude-code", "cursor", "vscode", "codex", "other"]
    desktop = json.loads(next(c for c in data["clients"] if c["id"] == "claude-desktop")["snippet"])
    entry = desktop["mcpServers"]["market-mirror"]
    assert entry["args"] == [str(server)]
    assert entry["env"] == {"MARKET_MIRROR_HOME": str(setup.ROOT)}
    vscode = json.loads(next(c for c in data["clients"] if c["id"] == "vscode")["snippet"])
    assert vscode["servers"]["market-mirror"]["type"] == "stdio"
    code = next(c for c in data["clients"] if c["id"] == "claude-code")["snippet"]
    # Name first, then options, then -- and the command: a name right after --env is read as another KEY=value.
    assert code.startswith("claude mcp add market-mirror --transport stdio --env ")
    assert code.index("--env ") < code.index(" -- ") and code.split(" -- ", 1)[1].endswith(str(server))
    # The HTTP transport is the server's own --http flag with a token file, and the token stays a placeholder.
    assert "--http --port 5061 --token-file" in data["http"]["start"]
    assert data["http"]["url"] == "http://127.0.0.1:5061/mcp"
    text = json.dumps(data)
    assert "sk-live-secret" not in text
    assert setup.SETUP_TOKEN not in text
    assert "<token from your token file>" in data["http"]["snippet"]


def test_codex_snippet_is_valid_toml_for_any_path():
    import tomllib
    from app.services.workspace_mcp_setup import _toml_string
    for path in ["/home/me/🚀 apps/mm", 'C:\\Users\\me\\"quoted"', "/tmp/tab\there", "/tmp/del\x7f", "/tmp/é"]:
        assert tomllib.loads(f"x = {_toml_string(path)}")["x"] == path
    assert _toml_string("/a/🚀") == '"/a/🚀"'


# ---------------------------------------------------------------- check an MCP server before saving it

@pytest.fixture
def transport(monkeypatch):
    calls = []

    def http(url, payload, headers):
        calls.append((url, payload, dict(headers)))
        if payload["method"] == "initialize":
            return {"jsonrpc": "2.0", "id": payload["id"], "result": {"protocolVersion": "2025-11-25"}}, {}
        if payload["method"] == "notifications/initialized":
            return {}, {}
        if payload["method"] == "tools/list":
            tools = [{"name": "report_read", "description": "Read", "annotations": {"readOnlyHint": True}},
                     {"name": "budget_set", "description": "Change budget", "annotations": {"destructiveHint": True, "openWorldHint": True}},
                     {"name": "plain"}]
            return {"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": tools}}, {}
        raise AssertionError(payload["method"])

    monkeypatch.setattr(mcp, "_http", http)
    return calls


def test_check_before_saving_saves_nothing_and_reports_hints(client, transport, tmp_path):
    response = client.post("/api/workspace/connectors/test", headers=H,
                           json={"url": "https://mcp.example.com/mcp", "token": "draft-secret-token"})
    data = response.json["data"]
    assert response.status_code == 200
    assert data["status"] == "connected"
    tools = {tool["name"]: tool for tool in data["tools"]}
    assert tools["report_read"]["read_only"] is True
    assert tools["budget_set"]["destructive"] is True and tools["budget_set"]["open_world"] is True
    assert tools["plain"] == {"name": "plain", "description": "", "read_only": False, "destructive": False, "open_world": False}
    assert transport[0][2]["Authorization"] == "Bearer draft-secret-token"
    assert "draft-secret-token" not in response.get_data(as_text=True)
    assert client.get("/api/workspace/connectors", headers=H).json["data"] == []
    assert not (tmp_path / "workspace_connectors.json").exists()


def test_check_refuses_private_addresses_and_bad_fields(client, transport):
    assert client.post("/api/workspace/connectors/test", headers=H, json={"url": "http://127.0.0.1:5061/mcp"}).status_code == 400
    assert client.post("/api/workspace/connectors/test", headers=H, json={"url": "https://mcp.example.com/mcp", "headers": {}}).status_code == 400
    assert not transport


def test_saved_token_only_goes_to_its_saved_address(client, transport):
    saved = client.post("/api/workspace/connectors", headers=H,
                        json={"name": "Ads", "url": "https://mcp.example.com/mcp", "token": "saved-secret-token"}).json["data"]
    same = client.post(f"/api/workspace/connectors/test?connector={saved['id']}", headers=H, json={"url": "https://mcp.example.com/mcp"})
    assert same.json["data"]["status"] == "connected"
    assert transport[0][2]["Authorization"] == "Bearer saved-secret-token"
    transport.clear()
    moved = client.post(f"/api/workspace/connectors/test?connector={saved['id']}", headers=H, json={"url": "https://other.example.com/mcp"})
    assert moved.status_code == 400
    assert "saved token" in moved.json["error"]
    assert not transport


def test_saving_a_new_address_does_not_keep_the_saved_token(client, transport, tmp_path):
    saved = client.post("/api/workspace/connectors", headers=H,
                        json={"name": "Ads", "url": "https://mcp.example.com/mcp", "token": "saved-secret-token"}).json["data"]
    stored = (tmp_path / "workspace_connectors.json").read_text()
    moved = client.patch(f"/api/workspace/connectors/{saved['id']}", headers=H, json={"name": "Ads", "url": "https://other.example.com/mcp"})
    assert moved.status_code == 400
    assert "The saved token is only sent to the saved address." in moved.json["error"]
    assert (tmp_path / "workspace_connectors.json").read_text() == stored
    # A blank token in the same request is not a new token.
    blank = client.patch(f"/api/workspace/connectors/{saved['id']}", headers=H, json={"url": "https://other.example.com/mcp", "token": ""})
    assert blank.status_code == 400
    assert not transport
    # The same address, or other fields, keep the saved token.
    assert client.patch(f"/api/workspace/connectors/{saved['id']}", headers=H, json={"name": "Ads 2", "url": "https://mcp.example.com/mcp"}).status_code == 200
    # A new token, or clearing the token, allows the move.
    retyped = client.patch(f"/api/workspace/connectors/{saved['id']}", headers=H, json={"url": "https://other.example.com/mcp", "token": "new-token"})
    assert retyped.status_code == 200 and retyped.json["data"]["url"] == "https://other.example.com/mcp"
    assert json.loads((tmp_path / "workspace_connectors.json").read_text())[0]["token"] == "new-token"
    cleared = client.patch(f"/api/workspace/connectors/{saved['id']}", headers=H, json={"url": "https://third.example.com/mcp", "clear_token": True})
    assert cleared.status_code == 200 and cleared.json["data"]["token_configured"] is False
    # Without a saved token there is nothing to protect.
    assert client.patch(f"/api/workspace/connectors/{saved['id']}", headers=H, json={"url": "https://fourth.example.com/mcp"}).status_code == 200


def test_check_reports_auth_errors_in_plain_words(client, monkeypatch):
    def denied(url, payload, headers):
        raise mcp.ConnectorAuthenticationError("Authentication required or account access denied. Check the bearer token and provider permissions.")
    monkeypatch.setattr(mcp, "_http", denied)
    data = client.post("/api/workspace/connectors/test", headers=H, json={"url": "https://mcp.example.com/mcp", "token": "wrong"}).json["data"]
    assert data["status"] == "auth_required"
    assert "bearer token" in data["error"]


def test_discovery_keeps_tool_hints(client, transport):
    saved = client.post("/api/workspace/connectors", headers=H, json={"name": "Ads", "url": "https://mcp.example.com/mcp"}).json["data"]
    tools = client.post(f"/api/workspace/connectors/{saved['id']}/discover", headers=H).json["data"]["tools"]
    assert {t["name"]: t["destructive"] for t in tools} == {"report_read": False, "budget_set": True, "plain": False}


# ---------------------------------------------------------------- free key check for model providers

@pytest.fixture
def provider(monkeypatch):
    calls = []
    answers = []

    def request(method, url, headers, body=None):
        calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        return answers.pop(0)

    monkeypatch.setattr(workspace_settings, "_test_request", request)
    return calls, answers


def test_key_check_lists_models_and_never_calls_a_model(client, provider):
    calls, answers = provider
    answers.append((200, {"data": [{"id": "gpt-a"}, {"id": "gpt-b"}]}))
    response = client.post("/api/workspace/settings/test", headers=H, json={"provider": "openai", "api_key": "sk-typed-secret"})
    data = response.json["data"]
    assert data["ok"] is True and data["status"] == "connected" and data["models"] == ["gpt-a", "gpt-b"]
    assert "Nothing was charged" in data["message"]
    assert calls == [{"method": "GET", "url": "https://api.openai.com/v1/models",
                      "headers": {"Accept": "application/json", "Content-Type": "application/json", "Authorization": "Bearer sk-typed-secret"},
                      "body": None}]
    assert "sk-typed-secret" not in response.get_data(as_text=True)


def test_anthropic_key_check_uses_its_own_header(client, provider):
    calls, answers = provider
    answers.append((200, {"data": [{"id": "claude-haiku-4-5"}]}))
    client.post("/api/workspace/settings/test", headers=H, json={"provider": "claude", "api_key": "sk-ant-typed"})
    assert calls[0]["url"] == "https://api.anthropic.com/v1/models"
    assert calls[0]["headers"]["x-api-key"] == "sk-ant-typed"
    assert "Authorization" not in calls[0]["headers"]


def test_rejected_key_is_reported_plainly(client, provider):
    _, answers = provider
    answers.append((401, {"error": {"message": "invalid key sk-typed"}}))
    data = client.post("/api/workspace/settings/test", headers=H, json={"provider": "openai", "api_key": "sk-typed"}).json["data"]
    assert data == {"ok": False, "status": "key_rejected", "method": "models_list",
                    "message": "OpenAI rejected this key. Check it was copied in full and is still active."}


def test_no_models_list_asks_before_a_small_call(client, provider):
    calls, answers = provider
    body = {"provider": "custom", "base_url": "https://llm.example.com/v1", "api_key": "typed", "model": "m1"}
    answers.append((404, None))
    data = client.post("/api/workspace/settings/test", headers=H, json=body).json["data"]
    assert data["status"] == "needs_call" and data["ok"] is None
    assert [c["method"] for c in calls] == ["GET"]
    answers.extend([(404, None), (200, {"choices": []})])
    data = client.post("/api/workspace/settings/test", headers=H, json={**body, "allow_call": True}).json["data"]
    assert data["status"] == "connected" and data["method"] == "one_call"
    assert calls[-1]["method"] == "POST" and calls[-1]["body"]["max_tokens"] == 1


def test_saved_key_is_not_sent_to_a_new_address(client, provider, monkeypatch):
    calls, answers = provider
    monkeypatch.setenv("OPENAI_API_KEY", "sk-saved-secret")
    response = client.post("/api/workspace/settings/test", headers=H, json={"provider": "openai", "base_url": "https://collector.example.com/v1"})
    assert response.status_code == 400
    assert "Type the key again" in response.json["error"]
    assert not calls
    answers.append((200, {"data": []}))
    assert client.post("/api/workspace/settings/test", headers=H, json={"provider": "openai"}).json["data"]["ok"] is True
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-saved-secret"


def test_saved_key_check_uses_the_configured_key_first(client, provider, monkeypatch):
    calls, answers = provider
    monkeypatch.setenv("OPENAI_API_KEY", "sk-provider-variable")
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-configured-key")
    answers.append((200, {"data": []}))
    client.post("/api/workspace/settings/test", headers=H, json={"provider": "openai"})
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-configured-key"


def test_slow_key_check_response_hits_a_whole_response_deadline(monkeypatch):
    import urllib3

    class Drip:
        status = 200

        def read1(self, amount, decode_content=True):
            return b" "

        def release_conn(self):
            pass

    monkeypatch.setattr(urllib3.PoolManager, "request", lambda self, *a, **k: Drip())
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(workspace_settings.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        workspace_settings._test_request("GET", "https://api.openai.com/v1/models", {})


def test_unreachable_server_hides_transport_text(client, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("connection refused for https://x?key=sk-leak")
    monkeypatch.setattr(workspace_settings, "_test_request", boom)
    response = client.post("/api/workspace/settings/test", headers=H, json={"provider": "openai", "api_key": "sk-leak"})
    assert response.json["data"]["status"] == "unreachable"
    assert "sk-leak" not in response.get_data(as_text=True)


def test_key_check_is_read_only_in_production(client, provider, monkeypatch):
    monkeypatch.setenv("MM_ENV", "production")
    calls, _ = provider
    response = client.post("/api/workspace/settings/test", headers=H, json={"provider": "openai", "api_key": "sk"})
    assert response.status_code == 400
    assert not calls


def test_key_check_needs_the_setup_token(client, provider):
    calls, _ = provider
    assert client.post("/api/workspace/settings/test", json={"provider": "openai", "api_key": "sk"}).status_code == 403
    assert not calls

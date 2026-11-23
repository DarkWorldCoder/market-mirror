"""Remote MCP configuration and transport boundaries; no external accounts contacted."""
import json
from types import SimpleNamespace

import pytest

from app import create_app
from app.api import setup
from app.config import Config
from app.services import workspace_connectors as mcp

H = {"X-Setup-Token": "connector-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(setup, "SETUP_TOKEN", "connector-test")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def transport(monkeypatch):
    calls = []
    def http(url, payload, headers):
        calls.append((url, payload, dict(headers)))
        method = payload["method"]
        if method == "initialize":
            value = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
        elif method == "notifications/initialized":
            return {}, {}
        elif method == "tools/list":
            value = {"tools": [{"name": "ads_read", "description": "Read report secret-token", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
                               {"name": "ads_write", "description": "Change ad budget", "annotations": {"readOnlyHint": False}}]}
        elif method == "tools/call":
            value = {"content": [{"type": "text", "text": "Actual saved response secret-token"}]}
        else:
            raise AssertionError(method)
        return {"jsonrpc": "2.0", "id": payload["id"], "result": value}, {"Mcp-Session-Id": "session-123"}
    monkeypatch.setattr(mcp, "_http", http)
    return calls


def create(client, **extra):
    response = client.post("/api/workspace/connectors", headers=H, json={"name": "Ads", "url": "https://mcp.example.com/mcp", "token": "secret-token", **extra})
    assert response.status_code == 201
    assert "secret-token" not in response.get_data(as_text=True)
    return response.json["data"]


def test_crud_discovery_secret_and_explicit_read_only_execution(client, transport, tmp_path):
    connector = create(client)
    assert connector["status"] == "not_tested"
    assert connector["enabled"] is False
    assert connector["allowed_tools"] == []
    assert not transport
    connector_id = connector["id"]
    assert (tmp_path / "workspace_connectors.json").stat().st_mode & 0o777 == 0o600
    result = client.post(f"/api/workspace/connectors/{connector_id}/discover", headers=H).json["data"]
    assert result["status"] == "connected"
    assert result["token_configured"] is True
    assert "secret-token" not in json.dumps(result)
    assert [call[1]["method"] for call in transport] == ["initialize", "notifications/initialized", "tools/list"]
    assert transport[-1][2]["Mcp-Session-Id"] == "session-123"
    assert transport[-1][2]["Authorization"] == "Bearer secret-token"
    with pytest.raises(mcp.ConnectorError):
        mcp.call_tool(connector_id, "ads_read", {})
    assert client.patch(f"/api/workspace/connectors/{connector_id}", headers=H, json={"enabled": True, "allowed_tools": ["ads_read", "ads_write"]}).status_code == 200
    result = mcp.call_tool(connector_id, "ads_read", {"account": "my-account"})
    assert "Actual saved response" in result["result"]
    assert "secret-token" not in result["result"]
    with pytest.raises(mcp.ConnectorError, match="readOnlyHint"):
        mcp.call_tool(connector_id, "ads_write", {})
    assert sum(call[1]["method"] == "tools/call" for call in transport) == 1
    assert client.delete(f"/api/workspace/connectors/{connector_id}", headers=H).status_code == 200
    assert client.get("/api/workspace/connectors", headers=H).json["data"] == []


def test_secrets_changes_reset_discovery_and_allowlist(client, transport):
    connector_id = create(client)["id"]
    client.post(f"/api/workspace/connectors/{connector_id}/discover", headers=H)
    client.patch(f"/api/workspace/connectors/{connector_id}", headers=H, json={"enabled": True, "allowed_tools": ["ads_read"]})
    result = client.patch(f"/api/workspace/connectors/{connector_id}", headers=H, json={"token": "new-token"}).json["data"]
    assert result["status"] == "not_tested"
    assert result["tools"] == result["allowed_tools"] == []
    assert result["token_configured"] is True
    assert client.patch(f"/api/workspace/connectors/{connector_id}", headers=H, json={"clear_token": True}).json["data"]["token_configured"] is False


@pytest.mark.parametrize("value", ["http://public.example/mcp", "https://localhost/mcp", "https://127.0.0.1/mcp", "https://169.254.169.254/token", "https://10.0.0.1/mcp", "https://[::1]/mcp", "https://224.0.0.1/mcp", "https://[fec0::1]/mcp", "https://[2002:7f00:1::]/mcp", "https://user:key@example.com/mcp", "https://example.com/mcp?token=secret", "https://example.com:bad/mcp"])
def test_endpoint_validation_no_network(client, monkeypatch, value):
    monkeypatch.setattr(mcp, "_http", lambda *args: pytest.fail("invalid endpoint must not be contacted"))
    assert client.post("/api/workspace/connectors", headers=H, json={"name": "Bad", "url": value}).status_code == 400


def test_auth_and_csrf(client):
    assert client.get("/api/workspace/connectors").status_code == 403
    assert client.get("/api/workspace/connectors", headers=H, environ_base={"REMOTE_ADDR": "10.0.0.1"}).status_code == 403
    assert client.post("/api/workspace/connectors", headers={**H, "Origin": "https://evil.example"}, json={}).status_code == 403


def test_dns_private_answers_blocked_before_http(monkeypatch):
    monkeypatch.setattr(mcp.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(mcp.ConnectorError, match="public addresses"):
        mcp._resolve("https://public-looking.example/mcp")


def test_transport_pins_public_address_rejects_redirect_and_parses_sse(monkeypatch):
    monkeypatch.setattr(mcp, "_resolve", lambda url: (__import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url), "93.184.216.34"))
    calls = []
    packets = [b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n',
               b'data: {"jsonrpc":"2.0","id":3,"result":{"tools":[]}}\n\n']
    class Pool:
        def __init__(self, address, **kwargs):
            assert address == "93.184.216.34"
            assert kwargs["server_hostname"] == kwargs["assert_hostname"] == "public.example"
        def urlopen(self, method, path, **kwargs):
            calls.append(kwargs)
            assert kwargs["redirect"] is False
            assert kwargs["headers"]["Host"] == "public.example"
            return SimpleNamespace(status=200, headers={"Content-Type": "text/event-stream"}, read1=lambda *args, **kwargs: packets.pop(0))
        def close(self):
            pass
    monkeypatch.setattr(mcp.urllib3, "HTTPSConnectionPool", Pool)
    result, _ = mcp._http("https://public.example/mcp", {"id": 3}, {})
    assert result["result"] == {"tools": []}
    assert len(calls) == 1


def test_discovery_error_stored_without_echoing_transport_secrets(client, monkeypatch):
    connector_id = create(client)["id"]
    def fail(*args):
        raise mcp.ConnectorError("Authorization failed")
    monkeypatch.setattr(mcp, "_http", fail)
    result = client.post(f"/api/workspace/connectors/{connector_id}/discover", headers=H).json["data"]
    assert result["status"] == "error"
    assert result["error"] == "Authorization failed"
    assert "secret-token" not in json.dumps(result)


def test_auth_required_is_real_failure_not_connected(client, monkeypatch):
    connector_id = create(client)["id"]
    def fail(*args):
        raise mcp.ConnectorAuthenticationError("Authentication required")
    monkeypatch.setattr(mcp, "_http", fail)
    data = client.post(f"/api/workspace/connectors/{connector_id}/discover", headers=H).json["data"]
    assert data["status"] == "auth_required"
    assert data["tools"] == []


def test_http_redirect_and_auth_status_do_not_follow_or_reflect_body(monkeypatch):
    monkeypatch.setattr(mcp, "_resolve", lambda url: (__import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url), "93.184.216.34"))
    status = [302]
    class Pool:
        def __init__(self, *args, **kwargs):
            pass
        def urlopen(self, *args, **kwargs):
            assert kwargs["redirect"] is False
            return SimpleNamespace(status=status[0], headers={}, read1=lambda *args, **kwargs: pytest.fail("must not read redirect or auth body"))
        def close(self):
            pass
    monkeypatch.setattr(mcp.urllib3, "HTTPSConnectionPool", Pool)
    with pytest.raises(mcp.ConnectorError, match="HTTP 302"):
        mcp._http("https://public.example/mcp", {"id": 1}, {})
    status[0] = 401
    with pytest.raises(mcp.ConnectorAuthenticationError):
        mcp._http("https://public.example/mcp", {"id": 1}, {})

"""Portable agent package and MCP message compatibility."""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[3]
SERVER = ROOT / "plugin/skills/market-mirror/scripts/mcp_server.py"
spec = importlib.util.spec_from_file_location("market_mcp", SERVER)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


def test_portable_manifest_and_canonical_skill():
    manifest = json.loads((ROOT / "plugin/plugin.json").read_text())
    mcp_manifest = json.loads((ROOT / "plugin/mcp.json").read_text())
    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    assert manifest["name"] == "market-mirror"
    assert mcp_manifest["mcpServers"]["market-mirror"]["type"] == "stdio"
    assert marketplace["plugins"][0]["source"]["path"] == "./plugin"
    assert (ROOT / "codex/skills/market-mirror/SKILL.md").resolve() == (ROOT / "plugin/skills/market-mirror/SKILL.md").resolve()
    for skill in ("research", "planning", "testing", "evidence-review"):
        assert (ROOT / "plugin/skills" / skill / "SKILL.md").is_file()


def test_mcp_initialize_tools_and_structured_error():
    init = mcp.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-03-26", "capabilities": {}}})
    assert init["result"]["protocolVersion"] == "2025-03-26"
    listed = mcp.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"campaign_plan", "actuals_import", "holdout_backtest", "website_test", "study", "predict", "results"} <= names
    err = mcp.dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "no_such_tool", "arguments": {}}})
    assert err["result"]["isError"] is True
    assert err["result"]["structuredContent"]["error_type"] == "ValueError"
    assert mcp.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_stdio_generic_client():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    p = subprocess.run([sys.executable, str(SERVER)], input="\n".join(json.dumps(m) for m in messages) + "\n",
                       capture_output=True, text=True, timeout=10)
    assert p.returncode == 0
    replies = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[0]["result"]["protocolVersion"] == "2024-11-05"


def test_loopback_http_requires_bearer_and_serves_mcp(monkeypatch):
    servers = []
    original = mcp.ThreadingHTTPServer

    def capture(address, handler):
        server = original(address, handler)
        servers.append(server)
        return server

    monkeypatch.setattr(mcp, "ThreadingHTTPServer", capture)
    token = "local-test-token-0123456789abcdef"
    thread = threading.Thread(target=mcp.serve_http, args=(0, token), daemon=True)
    thread.start()
    for _ in range(100):
        if servers:
            break
        thread.join(0.01)
    assert servers
    server = servers[0]
    url = f"http://127.0.0.1:{server.server_port}/mcp"
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body), timeout=2) as response:
            assert response.status == 401
    except urllib.error.HTTPError as error:
        assert error.code == 401
    try:
        request = urllib.request.Request(url, body, headers={"Authorization": "Bearer " + token,
                                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=2) as response:
            result = json.load(response)
        assert result["result"]["protocolVersion"] == "2025-06-18"
    finally:
        server.shutdown()
        server.server_close()

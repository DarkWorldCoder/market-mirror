"""Read-only browser snapshots, guarded artifacts and the public fetch boundary."""
import json
import socket
import sys
import time
from types import SimpleNamespace

import pytest

from app import create_app
from app.api import setup
from app.config import Config
from app.services import workspace_browser as browser

H = {"X-Setup-Token": "browser-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(setup, "SETUP_TOKEN", "browser-test")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_missing_browser_returns_actionable_error_without_fake_capture(client, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    response = client.post("/api/workspace/browser/observe", headers=H, json={"url": "https://example.com"})
    assert response.status_code == 400
    assert "browser extra" in response.json["error"]
    assert not (tmp_path / "workspace_browser").exists()


@pytest.mark.parametrize("value", [None, [], {}, {"url": "file:///etc/passwd"}, {"url": "https://user:secret@example.com"}, {"url": "https://example.com", "javascript": "steal()"}])
def test_browser_input_is_bounded_and_not_arbitrary_code(client, value):
    assert client.post("/api/workspace/browser/observe", headers=H, json=value).status_code == 400


def test_guard_and_private_png_paths(client, tmp_path):
    assert client.post("/api/workspace/browser/observe", json={"url": "https://example.com"}).status_code == 403
    assert client.post("/api/workspace/browser/observe", headers={**H, "Origin": "https://evil.example"}, json={}).status_code == 403
    session_id = "br_" + "a" * 24
    folder = tmp_path / "workspace_browser" / session_id
    folder.mkdir(parents=True)
    (folder / "observation.json").write_text("{}")
    (folder / "frame-0.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert client.get(f"/api/workspace/browser/{session_id}/image").status_code == 403
    response = client.get(f"/api/workspace/browser/{session_id}/image", headers=H)
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get(f"/api/workspace/browser/{session_id}/image?frame=../../secret", headers=H).status_code == 404
    assert client.get("/api/workspace/browser/br_invalid/image", headers=H).status_code == 404


def test_route_blocks_writes_scripts_and_never_continues(monkeypatch):
    calls = []
    route = SimpleNamespace(request=SimpleNamespace(method="POST", resource_type="document", url="https://example.com"), abort=lambda: calls.append("abort"))
    monkeypatch.setattr(browser, "_fetch", lambda *args: pytest.fail("POST must never reach fetch"))
    browser._route(route, {}, [])
    assert calls == ["abort"]
    route.request.method = "GET"
    route.request.resource_type = "script"
    browser._route(route, {}, [])
    assert calls == ["abort", "abort"]


def test_every_get_is_fetched_by_guard_then_fulfilled(monkeypatch):
    calls = []
    monkeypatch.setattr(browser, "_fetch", lambda url, budget: (200, {"Content-Type": "text/html"}, b"<h1>Real response</h1>"))
    route = SimpleNamespace(request=SimpleNamespace(method="GET", resource_type="document", url="https://example.com"),
                            fulfill=lambda **kwargs: calls.append(kwargs), abort=lambda: pytest.fail("valid result should fulfill"))
    browser._route(route, {}, [])
    assert calls[0]["body"] == b"<h1>Real response</h1>"


def test_fetch_pins_tls_hostname_does_not_forward_browser_credentials_and_blocks_private_redirect(monkeypatch):
    calls = []
    def target(url):
        if "127.0.0.1" in url:
            raise ValueError("private destination")
        return __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url), "93.184.216.34"
    monkeypatch.setattr(browser, "_public_target", target)
    class Pool:
        def __init__(self, address, **kwargs):
            assert address == "93.184.216.34"
            assert kwargs["server_hostname"] == kwargs["assert_hostname"] == "example.com"
        def urlopen(self, method, path, **kwargs):
            assert method == "GET" and kwargs["redirect"] is False
            assert "Authorization" not in kwargs["headers"] and "Cookie" not in kwargs["headers"]
            calls.append(kwargs)
            return SimpleNamespace(status=302, headers={"Location": "http://127.0.0.1/private"}, close=lambda: None)
        def close(self):
            pass
    monkeypatch.setattr(browser.urllib3, "HTTPSConnectionPool", Pool)
    with pytest.raises(ValueError, match="private"):
        browser._fetch("https://example.com", {"deadline": time.monotonic() + 10, "requests": 0, "bytes": 0})
    assert len(calls) == 1


def test_native_browser_proxy_never_forwards_connect():
    with browser._deny_proxy() as proxy:
        port = int(proxy["server"].rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(b"CONNECT 169.254.169.254:80 HTTP/1.1\r\nHost: 169.254.169.254\r\n\r\n")
            assert b"403" in connection.recv(1024)
        assert proxy["bypass"] == "<-loopback>"


def test_retention_removes_old_observations_only(client, tmp_path):
    root = tmp_path / "workspace_browser"
    root.mkdir()
    for i in range(12):
        folder = root / ("br_" + format(i, "024x"))
        folder.mkdir()
        (folder / "observation.json").write_text("{}")
    unrelated = root / "keep-other-data"
    unrelated.mkdir()
    browser._cleanup()
    assert len(list(root.glob("br_*"))) == 10
    assert unrelated.is_dir()

"""Model inventory is actual local metadata or an explicit offline connection choice, never inference."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

import pytest

from app.config import Config
from app.api import setup
from app.services import workspace_chat as chat, workspace_local_models as local


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("MM_WORKER_SECRET", raising=False)
    monkeypatch.setattr(setup, "LOGS", tmp_path)
    monkeypatch.setattr(setup, "_find_bin", lambda backend: None)
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[]))
    monkeypatch.setattr(chat, "_gateway_health", lambda port: None)
    monkeypatch.setattr(local, "cached_local_models", lambda: [])
    return tmp_path


@pytest.fixture
def metadata_server():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") != "Bearer correct-token":
                self.send_response(401); self.end_headers(); return
            body = json.dumps({"data": [{"id": "sonnet"}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            pytest.fail("Model discovery must never send inference")
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server.server_port, calls
    server.shutdown();server.server_close();thread.join()


def test_actual_gateway_metadata_requires_valid_bearer_without_inference(metadata_server):
    port, calls = metadata_server
    assert chat._gateway_models(port, "wrong-token") is None
    assert chat._gateway_models(port, "correct-token") == ["sonnet"]
    assert calls == [("/v1/models", "Bearer wrong-token"), ("/v1/models", "Bearer correct-token")]


def test_legacy_default_gateway_token_discovery_verifies_catalog(isolated, monkeypatch, metadata_server):
    port, calls = metadata_server
    real = chat._gateway_models
    monkeypatch.setattr(chat, "_gateway_models", lambda candidate, key: real(port, key) if candidate == 5055 else None)
    monkeypatch.setattr(chat, "_gateway_health", lambda candidate: {"backend": "claude", "model": "sonnet", "available": True, "auth_required": True} if candidate == 5055 else None)
    (isolated / "gateway.token").write_text("wrong-token")
    assert all(not row["available"] for row in chat.models()["models"])
    (isolated / "gateway.token").write_text("correct-token")
    rows = chat.models()["models"]
    assert {row["model"] for row in rows} == {"sonnet", "haiku", "opus"}
    assert all(row["available"] for row in rows)
    assert "correct-token" not in json.dumps(rows)
    assert all(path == "/v1/models" for path, _ in calls)


def test_configured_running_and_discovered_identical_route_deduplicates(isolated, monkeypatch):
    slot = NS(provider="openai", model="gemini-real", base_url="http://127.0.0.1:5057/v1", api_key="secret")
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[slot]))
    monkeypatch.setattr(chat, "_gateway_health", lambda port: {"backend": "antigravity", "model": "gemini-real", "available": True, "auth_required": True} if port == 5057 else None)
    monkeypatch.setattr(chat, "_gateway_models", lambda port, key: ["gemini-real"] if port == 5057 and key == "secret" else None)
    monkeypatch.setattr(local, "cached_local_models", lambda: [{"provider": "configured", "id": "gemini-real", "base_url": "http://localhost:5057/v1"}])
    monkeypatch.setattr(local, "key_for_local_model", lambda url: "secret")
    rows = chat.models()["models"]
    assert len(rows) == 1
    assert rows[0]["provider"] == "antigravity"
    assert rows[0]["available"] is True


def test_installed_claude_offline_is_connectable_not_entitled(isolated, monkeypatch):
    monkeypatch.setattr(setup, "_find_bin", lambda backend: "/installed/claude" if backend == "claude" else None)
    rows = chat.models()["models"]
    assert {row["model"] for row in rows} == {"sonnet", "haiku", "opus"}
    # The local app starts the login on the first message; it never claims the login is already connected.
    assert all(row["available"] and row["status"] == "connect_on_first_use" and row["connection_required"]
               and row["connection_backend"] == "claude" for row in rows)
    monkeypatch.setenv("MM_ENV", "production")
    assert chat.models()["models"] == []


def test_hosted_worker_never_probes_local_cli_ports_files_or_cache(isolated, monkeypatch):
    monkeypatch.setenv("MM_WORKER_SECRET", "private-worker")
    slot = NS(provider="openai", model="hosted-private", base_url="http://control:8080/hosted/v1", api_key="private-worker")
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=[slot]))
    monkeypatch.setattr(chat, "_gateway_health", lambda *a: pytest.fail("hosted worker must not scan ports"))
    monkeypatch.setattr(chat, "_gateway_models", lambda *a: pytest.fail("hosted worker must not read local catalogs"))
    monkeypatch.setattr(setup, "_find_bin", lambda *a: pytest.fail("hosted worker must not inspect host CLIs"))
    monkeypatch.setattr(local, "cached_local_models", lambda: pytest.fail("hosted worker must not expose cached local models"))
    class NoFiles:
        def glob(self, *args):
            pytest.fail("hosted worker must not read local gateway files")
    monkeypatch.setattr(setup, "LOGS", NoFiles())
    rows = chat.models()["models"]
    assert [row["model"] for row in rows] == ["hosted-private"]
    assert "private-worker" not in json.dumps(rows)



def test_all_native_codex_ids_are_listed_without_fabricated_names(isolated, monkeypatch):
    (isolated / "gateway-5056.token").write_text("codex-key")
    monkeypatch.setattr(chat, "_gateway_health", lambda port: {"backend": "codex", "model": "codex", "available": True, "auth_required": True} if port == 5056 else None)
    monkeypatch.setattr(chat, "_gateway_models", lambda port, key: ["gpt-real-model-a", "gpt-real-model-b"] if port == 5056 and key == "codex-key" else None)
    rows = chat.models()["models"]
    assert [row["model"] for row in rows] == ["gpt-real-model-a", "gpt-real-model-b"]
    assert all(row["available"] for row in rows)

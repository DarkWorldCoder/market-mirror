"""Only actual bounded loopback catalogs become selectable local models."""
import pytest
from app import create_app
from app.api import setup
from app.config import Config
from app.services import workspace_local_models as local

H = {"X-Setup-Token": "local-test"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(local, "_CACHE", None)
    monkeypatch.setattr(setup, "SETUP_TOKEN", "local-test")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://api.openai.com/v1")
    for key in ("MM_WORKER_SECRET", "MM_HOSTED_WORKER", "OLLAMA_BASE_URL", "LMSTUDIO_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_discovery_is_explicit_cached_and_actual(client, monkeypatch):
    calls = []
    def get(base, path, key=None):
        calls.append((base, path))
        return {"models": [{"name": "actually-installed:7b"}]} if path == "/api/tags" else {"data": [{"id": "real-studio-model"}]}
    monkeypatch.setattr(local, "_get", get)
    assert local.cached_local_models() == []
    assert not calls
    assert client.get("/api/workspace/local-models").status_code == 403
    result = client.get("/api/workspace/local-models", headers=H).json["data"]
    assert [row["id"] for row in result["models"]] == ["actually-installed:7b", "real-studio-model"]
    assert calls == [("http://127.0.0.1:11434/v1", "/api/tags"), ("http://127.0.0.1:1234/v1", "/v1/models")]
    assert local.cached_local_models() == result["models"]
    assert local.key_for_local_model(result["models"][0]["base_url"]) == "local"
    client.get("/api/workspace/local-models", headers=H)
    assert len(calls) == 2


def test_hosted_worker_does_not_probe_unconfigured_defaults(client, monkeypatch):
    monkeypatch.setenv("MM_WORKER_SECRET", "worker-secret")
    monkeypatch.setattr(local, "_get", lambda *args: pytest.fail("hosted worker must not scan defaults"))
    assert client.get("/api/workspace/local-models", headers=H).json["data"]["models"] == []


def test_configured_endpoint_uses_real_key_without_serializing_it(client, monkeypatch):
    monkeypatch.setenv("MM_WORKER_SECRET", "worker-secret")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://127.0.0.1:8088/v1")
    monkeypatch.setattr(Config, "LLM_API_KEY", "secret-local")
    def get(base, path, key=None):
        assert base == Config.LLM_BASE_URL and path == "/v1/models" and key == "secret-local"
        return {"data": [{"id": "self-hosted-model"}]}
    monkeypatch.setattr(local, "_get", get)
    response = client.get("/api/workspace/local-models", headers=H)
    assert "secret-local" not in response.get_data(as_text=True)
    assert response.json["data"]["models"][0]["provider"] == "configured"
    assert local.key_for_local_model("http://127.0.0.1:8088/v1") == "secret-local"
    with pytest.raises(ValueError):
        local.key_for_local_model("http://127.0.0.1:9999/v1")


@pytest.mark.parametrize("url", ["http://169.254.169.254:8080/v1", "http://192.168.0.1:8080/v1", "https://public.example/v1", "http://localhost:8080/admin", "http://user:key@127.0.0.1:8080/v1", "http://127.0.0.1:80/v1", "http://127.0.0.1:8080/v1?x=1"])
def test_discovery_target_rejects_arbitrary_requests(url):
    assert local._target(url) is None


def test_unavailable_server_does_not_invent_models(client, monkeypatch):
    def fail(*args):
        raise ValueError("Local model server is not reachable")
    monkeypatch.setattr(local, "_get", fail)
    data = client.get("/api/workspace/local-models", headers=H).json["data"]
    assert data["models"] == []
    assert all(not row["available"] for row in data["sources"])

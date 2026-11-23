"""Workspace project persistence and safe configuration; no provider network traffic."""
import json
import os

import pytest

from app import create_app
from app.api import setup
from app.config import Config
from app.models.project import ProjectManager
from app.services import workspace_settings
from app.utils import spend_cap
from app.utils.model_pool import PROVIDER_DEFAULTS

HEADERS = {"X-Setup-Token": "workspace-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "SETUP_TOKEN", "workspace-test")
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(workspace_settings, "_RESTART_REQUIRED", False)
    monkeypatch.setenv("MM_SPEND_FILE", str(tmp_path / "spend.json"))
    monkeypatch.setattr(spend_cap, "_PROCESS", {"spent_usd": 0.0, "calls": 0})
    for field in ("LLM_PROVIDER", "LLM_MODEL_NAME", "LLM_BASE_URL", "LLM_API_KEY", "LLM_POOL"):
        monkeypatch.setattr(Config, field, getattr(Config, field))
    for key in ("MM_MAX_SPEND_USD", "MM_USD_PER_MTOK", "LLM_PROVIDER", "LLM_MODEL_NAME", "LLM_BASE_URL", "LLM_API_KEY", "LLM_POOL", "LLM_GATEWAY"):
        monkeypatch.delenv(key, raising=False)
    for name, spec in PROVIDER_DEFAULTS.items():
        for key in (spec.get("key_env"), *spec.get("alt_key_envs", ()), f"{name.upper()}_MODEL_NAME", f"{name.upper()}_BASE_URL"):
            if key:
                monkeypatch.delenv(key, raising=False)
    for key in ("MEMORY_BACKEND", "MEMORY_EMBEDDINGS", "MEMORY_EXTRACT_ACTIVITY", "COGNEE_SIDECAR_URL", "ZEP_API_KEY"):
        monkeypatch.setattr(Config, key, getattr(Config, key))
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    for key in ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_VIA", "JEV_MODEL", "JEV_PARALLEL", "JEV_TIMEOUT", "JEV_RETRIES", "MM_JEV_LABELS", "SSR_ENGINE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MIROFISH_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(tmp_path / "runs"))
    (tmp_path / "runs" / "actual-run").mkdir(parents=True)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.mark.parametrize("path", ["/api/workspace/projects", "/api/workspace/settings"])
def test_configuration_protected(client, path):
    assert client.get(path).status_code == 403
    assert client.get(path, headers=HEADERS, environ_base={"REMOTE_ADDR": "10.0.0.5"}).status_code == 403
    verb = client.put if path.endswith("settings") else client.post
    assert verb(path, headers={**HEADERS, "Origin": "https://evil.example"}, json={}).status_code == 403


def test_create_update_associate_archive_persists(client):
    response = client.post("/api/workspace/projects", headers=HEADERS,
                           json={"name": "Growth", "instructions": "Prefer cited evidence", "chat_ids": ["chat-123"], "run_names": ["actual-run"]})
    assert response.status_code == 201
    project = response.json["data"]
    project_id = project["id"]
    engine = ProjectManager.get_project(project_id)
    assert engine.name == "Growth"
    stored = json.loads((__import__("pathlib").Path(ProjectManager.PROJECTS_DIR) / project_id / "workspace.json").read_text())
    assert stored["chat_ids"] == ["chat-123"]
    assert project["engine_project_id"] == engine.project_id
    assert client.get("/api/workspace/projects", headers=HEADERS).json["data"] == [project]
    updated = client.patch(f"/api/workspace/projects/{project_id}", headers=HEADERS,
                          json={"name": "Renamed", "description": "My workspace", "chat_ids": ["chat-123", "chat-456"]})
    assert updated.status_code == 200
    assert ProjectManager.get_project(project_id).name == "Renamed"
    assert client.get(f"/api/workspace/projects/{project_id}", headers=HEADERS).json["data"]["description"] == "My workspace"
    assert client.delete(f"/api/workspace/projects/{project_id}", headers=HEADERS).status_code == 200
    assert client.get("/api/workspace/projects", headers=HEADERS).json["data"] == []
    assert client.get(f"/api/workspace/projects/{project_id}", headers=HEADERS).status_code == 404
    assert ProjectManager.get_project(project_id) is not None


@pytest.mark.parametrize("payload", [None, [], {}, {"name": " "}, {"name": "x", "chat_ids": ["../../secret"]},
    {"name": "x", "run_names": ["missing"]}, {"name": "x", "run_names": ["../actual-run"]},
    {"name": "x", "api_key": "secret"}, {"name": "x" * 121}])
def test_projects_reject_bad_input(client, payload):
    assert client.post("/api/workspace/projects", json=payload, headers=HEADERS).status_code == 400
    assert client.get("/api/workspace/projects", headers=HEADERS).json["data"] == []


def test_settings_save_secret_private_and_unsupported_truthful(client, tmp_path):
    response = client.put("/api/workspace/settings", headers=HEADERS, json={
        "memory": {"backend": "zep", "zep_api_key": "private-zep", "embeddings": False},
        "jev": {"route": "typesafe", "api_key": "private-jev", "model": "jev-latest", "parallel": 2,
                "labels": "auto", "timeout": 45, "retries": 1, "ssr_engine": "jev"}})
    assert response.status_code == 200
    assert "private-zep" not in response.get_data(as_text=True)
    assert "private-jev" not in response.get_data(as_text=True)
    data = response.json["data"]
    assert data["memory"]["backend"] == "zep"
    assert data["memory"]["zep_key_configured"] is True
    assert data["jev"]["configured"] is True
    assert data["jev"]["parallel"] == 2
    assert data["restart_required"] is True
    assert data["connection_tested"] is False
    assert next(p for p in data["memory"]["providers"] if p["id"] == "supermemory")["supported"] is False
    env = tmp_path / ".env"
    assert env.stat().st_mode & 0o777 == 0o600
    assert 'TYPESAFE_API_KEY="private-jev"' in env.read_text()
    assert Config.ZEP_API_KEY == "private-zep"
    assert client.get("/api/workspace/settings", headers=HEADERS).headers["Cache-Control"] == "no-store"
    assert client.put("/api/workspace/settings", headers=HEADERS, json={"jev": {"api_key": ""}}).json["data"]["jev"]["configured"] is True


@pytest.mark.parametrize("payload", [None, [], {}, {"other": {}}, {"memory": {"backend": "supermemory"}},
    {"memory": {"backend": "zep"}}, {"memory": {"embeddings": "true"}},
    {"memory": {"cognee_url": "http://user:secret@localhost:8765"}},
    {"jev": {"api_key": "key\nINJECTED=true"}}, {"jev": {"parallel": True}},
    {"jev": {"parallel": 0}}, {"jev": {"timeout": 1}}, {"jev": {"retries": 9}},
    {"jev": {"route": "unknown"}}, {"jev": {"labels": "yes"}}])
def test_settings_validate_before_any_write(client, tmp_path, payload):
    assert client.put("/api/workspace/settings", headers=HEADERS, json=payload).status_code == 400
    assert not (tmp_path / ".env").exists()


def test_openrouter_key_uses_existing_native_route(client):
    result = client.put("/api/workspace/settings", headers=HEADERS,
                        json={"jev": {"route": "openrouter", "api_key": "router-secret", "model": "~typesafe/jev-latest"}})
    assert result.status_code == 200
    assert result.json["data"]["jev"]["configured"] is True
    assert result.json["data"]["jev"]["route"] == "openrouter"
    assert os.environ["OPENROUTER_API_KEY"] == "router-secret"


def test_existing_engine_projects_visible_and_editable(client):
    engine = ProjectManager.create_project("Existing graph project")
    data = client.get("/api/workspace/projects", headers=HEADERS).json["data"]
    assert data[0]["id"] == engine.project_id
    response = client.patch(f"/api/workspace/projects/{engine.project_id}", headers=HEADERS,
                            json={"instructions": "Keep the existing graph"})
    assert response.status_code == 200
    assert response.json["data"]["instructions"] == "Keep the existing graph"


def test_older_sidecar_url_credentials_never_exposed(client, monkeypatch):
    monkeypatch.setattr(Config, "COGNEE_SIDECAR_URL", "https://user:private-pass@localhost:8765/api?key=private-query#private-fragment")
    response = client.get("/api/workspace/settings", headers=HEADERS)
    assert response.json["data"]["memory"]["cognee_url"] == "https://localhost:8765/api"
    assert "private" not in response.get_data(as_text=True)



def test_model_configuration_applies_real_engine_fields_and_hides_key(client, tmp_path):
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"llm": {
        "provider": "openrouter", "model": "my-model", "base_url": "https://openrouter.ai/api/v1",
        "api_key": "private-cloud", "pool": "openrouter:my-model,claude"}})
    assert response.status_code == 200
    assert "private-cloud" not in response.get_data(as_text=True)
    assert Config.LLM_PROVIDER == "openrouter"
    assert Config.LLM_MODEL_NAME == "my-model"
    assert Config.LLM_API_KEY == "private-cloud"
    assert Config.LLM_POOL == "openrouter:my-model,claude"
    assert os.environ["OPENROUTER_API_KEY"] == "private-cloud"
    assert "LLM_GATEWAY" not in os.environ
    saved = client.put("/api/workspace/settings", headers=HEADERS, json={"llm": {"provider": "openrouter", "model": "second-model", "api_key": ""}})
    assert saved.status_code == 200
    assert Config.LLM_API_KEY == "private-cloud"
    assert Config.LLM_MODEL_NAME == "second-model"
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_ollama_needs_no_cloud_key(client):
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"llm": {"provider": "ollama", "model": "local-model"}})
    assert response.status_code == 200
    assert Config.LLM_API_KEY == "local"
    assert Config.LLM_BASE_URL == "http://127.0.0.1:11434/v1"


def test_legacy_pool_inline_keys_never_serialized(client, monkeypatch):
    monkeypatch.setattr(Config, "LLM_POOL", '[{"provider":"openai","api_key":"private-inline","model":"my-model","base_url":"https://user:password@example.com/v1?key=secret"}]')
    response = client.get("/api/workspace/settings", headers=HEADERS)
    assert "private-inline" not in response.get_data(as_text=True)
    assert "password" not in response.get_data(as_text=True)
    assert "key=secret" not in response.get_data(as_text=True)
    assert json.loads(response.json["data"]["llm"]["pool"])[0]["model"] == "my-model"


def test_process_budget_is_real_enforcement_and_does_not_reset_usage(client):
    spend_cap.charge_tokens("gpt-4o-mini", 1000000, 0)
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"spending": {"process_limit_usd": 0.1}})
    assert response.status_code == 200
    assert response.json["data"]["spending"]["process_spent_usd"] == 0.15
    assert response.json["data"]["spending"]["process_calls"] == 1
    with pytest.raises(spend_cap.SpendCapReached):
        spend_cap.check()
    assert client.put("/api/workspace/settings", headers=HEADERS, json={"spending": {"process_limit_usd": 0}}).status_code == 200
    spend_cap.check()
    assert spend_cap.process_spent()["calls"] == 1


def test_price_overrides_and_shared_run_cap_preserved(client):
    cap = spend_cap.arm(4, "existing workflow")
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"spending": {
        "process_limit_usd": 3, "input_price_usd_per_mtok": 2, "output_price_usd_per_mtok": 5}})
    assert response.status_code == 200
    assert spend_cap.price_for("unknown-model")[0] == (2, 5)
    assert response.json["data"]["spending"]["run_cap"]["cap_id"] == cap["cap_id"]
    assert client.put("/api/workspace/settings", headers=HEADERS, json={"spending": {
        "input_price_usd_per_mtok": None, "output_price_usd_per_mtok": None}}).status_code == 200
    assert "MM_USD_PER_MTOK" not in os.environ


@pytest.mark.parametrize("payload", [{"llm": {"provider": "bad"}}, {"llm": {"provider": "openai", "api_key": "key", "base_url": "https://user:secret@example.com"}},
    {"llm": {"pool": '[{"provider":"openai","api_key":"inline-key"}]'}}, {"llm": {"pool": "unknown"}},
    {"spending": {"process_limit_usd": -1}}, {"spending": {"process_limit_usd": True}},
    {"spending": {"input_price_usd_per_mtok": 2}}, {"spending": {"process_limit_usd": float("inf")}},
    {"spending": {"process_limit_usd": float("nan")}}])
def test_models_and_spending_validate_before_write(client, tmp_path, payload):
    assert client.put("/api/workspace/settings", headers=HEADERS, json=payload).status_code == 400
    assert not (tmp_path / ".env").exists()


def test_real_chat_client_charges_usage_and_process_budget_blocks_before_transport(client, monkeypatch):
    from types import SimpleNamespace
    from app.utils import llm_client
    calls = []
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"message":"hello"}'), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=1000000, completion_tokens=0))
    def create(**kwargs):
        calls.append(kwargs)
        return response
    fake = SimpleNamespace(base_url="https://api.openai.com/v1", chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm_client, "OpenAI", lambda **kwargs: fake)
    model = llm_client.LLMClient(api_key="test", model="gpt-4o-mini")
    assert client.put("/api/workspace/settings", headers=HEADERS, json={"spending": {"process_limit_usd": 0.1}}).status_code == 200
    assert model.chat_json([{"role": "user", "content": "Hello"}]) == {"message": "hello"}
    assert spend_cap.process_spent()["spent_usd"] == 0.15
    with pytest.raises(spend_cap.SpendCapReached):
        model.chat_json([{"role": "user", "content": "Hello again"}])
    assert len(calls) == 1


def test_env_interpolation_values_rejected(client, tmp_path):
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"jev": {"api_key": "${ANOTHER_SECRET}"}})
    assert response.status_code == 400
    assert not (tmp_path / ".env").exists()


def test_own_unauthenticated_compatible_model_uses_local_placeholder(client):
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"llm": {
        "provider": "custom", "model": "my-installed-model", "base_url": "http://127.0.0.1:1234/v1", "api_key": ""}})
    assert response.status_code == 200
    assert Config.LLM_API_KEY == "local"
    assert response.json["data"]["llm"]["api_key_configured"] is False


def test_switching_configured_loopback_to_custom_retains_its_exact_endpoint_key(client, monkeypatch):
    monkeypatch.setattr(Config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://127.0.0.1:8088/v1")
    monkeypatch.setattr(Config, "LLM_API_KEY", "local-server-secret")
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"llm": {
        "provider": "custom", "model": "installed-model", "base_url": "http://127.0.0.1:8088/v1", "api_key": ""}})
    assert response.status_code == 200
    assert Config.LLM_API_KEY == "local-server-secret"
    assert "local-server-secret" not in response.get_data(as_text=True)


def test_hosted_worker_credential_is_not_reused_as_a_byok_key(client, monkeypatch):
    monkeypatch.setenv("MM_WORKER_SECRET", "private-worker-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "private-worker-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://control:8080/hosted/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "hosted-private")
    monkeypatch.setattr(Config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://control:8080/hosted/v1")
    monkeypatch.setattr(Config, "LLM_API_KEY", "private-worker-secret")
    safe = client.get("/api/workspace/settings", headers=HEADERS).json["data"]
    assert safe["llm"]["api_key_configured"] is False
    provider = next(row for row in safe["llm"]["providers"] if row["id"] == "openai")
    assert provider["key_configured"] is False
    assert provider["base_url"] == "https://api.openai.com/v1"
    assert provider["model"] != "hosted-private"
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"llm": {
        "provider": "openai", "model": "my-model", "base_url": "https://api.openai.com/v1", "api_key": ""}})
    assert response.status_code == 400
    assert Config.LLM_BASE_URL == "http://control:8080/hosted/v1"


def test_control_plane_can_explicitly_select_its_hosted_credential(client, monkeypatch):
    monkeypatch.setenv("MM_WORKER_SECRET", "private-worker-secret")
    response = client.put("/api/workspace/settings", headers=HEADERS, json={"llm": {
        "provider": "openai", "model": "hosted-private", "base_url": "http://control:8080/hosted/v1", "api_key": "private-worker-secret"}})
    assert response.status_code == 200
    assert Config.LLM_API_KEY == "private-worker-secret"
    assert "private-worker-secret" not in response.get_data(as_text=True)

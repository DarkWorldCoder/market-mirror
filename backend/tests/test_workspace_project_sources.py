"""Persistent plain-text project knowledge and server-catalog model preferences."""
import json
from pathlib import Path

import pytest

from app import create_app
from app.api import setup
from app.models.project import ProjectManager

H = {"X-Setup-Token": "knowledge-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(setup, "SETUP_TOKEN", "knowledge-test")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def project(client):
    return client.post("/api/workspace/projects", headers=H, json={"name": "Launch", "instructions": "Cite evidence", "chat_ids": ["chat-a"], "preferred_model": "m_" + "a" * 24}).json["data"]


def test_knowledge_add_remove_persistence_preserves_preferences(client):
    original = project(client)
    url = f"/api/workspace/projects/{original['id']}"
    response = client.post(url + "/sources", headers=H, json={"name": "Buyer brief", "text": "  Evidence line.\nSecond line.  "})
    assert response.status_code == 201
    updated = response.json["data"]
    source = updated["sources"][0]
    assert source["text"] == "  Evidence line.\nSecond line.  "
    assert source["created_at"]
    assert updated["instructions"] == original["instructions"]
    assert updated["chat_ids"] == original["chat_ids"]
    assert updated["preferred_model"] == original["preferred_model"]
    metadata = Path(ProjectManager.PROJECTS_DIR) / original["id"] / "workspace.json"
    assert json.loads(metadata.read_text())["sources"] == updated["sources"]
    assert metadata.stat().st_mode & 0o777 == 0o600
    assert client.get(url, headers=H).json["data"]["sources"] == updated["sources"]
    assert client.delete(url + "/sources/" + source["id"], headers=H).json["data"]["sources"] == []
    assert client.delete(url + "/sources/" + source["id"], headers=H).status_code == 404


def test_existing_engine_project_receives_empty_knowledge_defaults(client):
    engine = ProjectManager.create_project("Existing")
    result = client.get(f"/api/workspace/projects/{engine.project_id}", headers=H).json["data"]
    assert result["sources"] == []
    assert result["preferred_model"] == ""


@pytest.mark.parametrize("data", [None, [], {}, {"name": "", "text": "x"}, {"name": "source", "text": " "},
    {"name": "source", "text": "x" * 24001}, {"name": "source", "text": "binary\0text"},
    {"name": "source", "text": "x", "url": "https://example.com"}, {"name": "bad\nname", "text": "x"}])
def test_source_fields_plain_text_only_and_bounded(client, data):
    value = project(client)
    response = client.post(f"/api/workspace/projects/{value['id']}/sources", headers=H, json=data)
    assert response.status_code == 400


def test_source_count_and_aggregate_limits(client):
    a = project(client)
    path = f"/api/workspace/projects/{a['id']}/sources"
    for index in range(5):
        assert client.post(path, headers=H, json={"name": str(index), "text": "x" * 24000}).status_code == 201
    assert client.post(path, headers=H, json={"name": "too much", "text": "x"}).status_code == 400
    b = project(client)
    path = f"/api/workspace/projects/{b['id']}/sources"
    for index in range(10):
        assert client.post(path, headers=H, json={"name": str(index), "text": "x"}).status_code == 201
    assert client.post(path, headers=H, json={"name": "extra", "text": "x"}).status_code == 400


def test_source_auth_origin_and_request_size(client):
    value = project(client)
    path = f"/api/workspace/projects/{value['id']}/sources"
    assert client.post(path, json={"name": "x", "text": "x"}).status_code == 403
    assert client.post(path, headers={**H, "Origin": "https://evil.example"}, json={"name": "x", "text": "x"}).status_code == 403
    assert client.post(path, headers=H, json={"name": "x", "text": "x" * 31000}).status_code == 413
    assert client.delete(path + "/src_invalid", headers=H).status_code == 404


@pytest.mark.parametrize("model", ["http://example.com", "gpt-model", {"base_url": "http://evil.example"}, "m_../path", "m_" + "a" * 25])
def test_preferred_model_is_only_server_catalog_pointer(client, model):
    value = project(client)
    assert client.patch(f"/api/workspace/projects/{value['id']}", headers=H, json={"preferred_model": model}).status_code == 400


def test_preferred_model_can_be_cleared_without_losing_sources(client):
    value = project(client)
    url = f"/api/workspace/projects/{value['id']}"
    client.post(url + "/sources", headers=H, json={"name": "Saved", "text": "Reference"})
    updated = client.patch(url, headers=H, json={"preferred_model": None}).json["data"]
    assert updated["preferred_model"] == ""
    assert updated["sources"][0]["text"] == "Reference"

"""Custom skills store instructions only. Tests make no provider or network calls."""
import json
import os

import pytest

from app import create_app
from app.api import setup
from app.config import Config

H = {"X-Setup-Token": "skills-test"}
PAYLOAD = {"name": "Weekly ad review", "description": "Review supplied advertising evidence", "instructions": "Use supplied evidence. Show which creative performed best and why.", "group": "Advertising", "source_url": "https://github.com/example/skills/blob/main/SKILL.md"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(setup, "SETUP_TOKEN", "skills-test")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_private_persistent_prompt_crud(client, tmp_path):
    assert client.get("/api/workspace/skills", headers=H).json["data"] == []
    response = client.post("/api/workspace/skills", headers=H, json=PAYLOAD)
    assert response.status_code == 201
    value = response.json["data"]
    identity = value["id"]
    assert identity.startswith("skill_")
    path = tmp_path / "workspace_skills" / f"{identity}.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(path.read_text())["instructions"] == PAYLOAD["instructions"]
    assert client.get(f"/api/workspace/skills/{identity}", headers=H).json["data"] == value
    assert client.get("/api/workspace/skills", headers=H).json["data"] == [value]
    updated = client.patch(f"/api/workspace/skills/{identity}", headers=H, json={"name": "Renamed"}).json["data"]
    assert updated["name"] == "Renamed"
    assert updated["instructions"] == PAYLOAD["instructions"]
    assert updated["created_at"] == value["created_at"]
    assert client.delete(f"/api/workspace/skills/{identity}", headers=H).status_code == 200
    assert not path.exists()
    assert client.get(f"/api/workspace/skills/{identity}", headers=H).status_code == 404
    assert client.get("/api/workspace/skills", headers=H).headers["Cache-Control"] == "no-store"


def test_token_loopback_and_origin_guards(client):
    assert client.get("/api/workspace/skills").status_code == 403
    assert client.get("/api/workspace/skills", headers=H, environ_base={"REMOTE_ADDR": "10.0.0.5"}).status_code == 403
    assert client.post("/api/workspace/skills", headers={**H, "Origin": "https://evil.example"}, json=PAYLOAD).status_code == 403


@pytest.mark.parametrize("change", [None, [], {}, {"name": "No instructions"}, {"name": "", "instructions": "x"}, {"name": "x", "instructions": " "}, {**PAYLOAD, "name": "x" * 121}, {**PAYLOAD, "description": "x" * 301}, {**PAYLOAD, "instructions": "x" * 12001}, {**PAYLOAD, "group": "../../outside"}, {**PAYLOAD, "source_url": "javascript:alert(1)"}, {**PAYLOAD, "source_url": "file:///etc/passwd"}, {**PAYLOAD, "source_url": "https://user:secret@example.com"}, {**PAYLOAD, "script": "arbitrary executable"}, {**PAYLOAD, "id": "built-in"}])
def test_rejects_invalid_input_before_write(client, tmp_path, change):
    assert client.post("/api/workspace/skills", headers=H, json=change).status_code == 400
    assert not (tmp_path / "workspace_skills").exists()


def test_instruction_limit_unicode_and_source_are_stored_as_text(client):
    instructions = "क" * 12000
    response = client.post("/api/workspace/skills", headers=H, json={"name": "Review", "instructions": instructions})
    assert response.status_code == 201
    assert response.json["data"]["instructions"] == instructions
    identity = response.json["data"]["id"]
    assert client.patch(f"/api/workspace/skills/{identity}", headers=H, json={"created_at": "overwrite"}).status_code == 400


def test_builtins_traversal_and_symlink_sources_are_not_custom_skills(client, tmp_path):
    assert client.delete("/api/workspace/skills/market-test", headers=H).status_code == 404
    assert client.get("/api/workspace/skills/..%2Fsecret", headers=H).status_code == 404
    root = tmp_path / "workspace_skills"
    root.mkdir()
    secret = tmp_path / "outside.json"
    secret.write_text(json.dumps({"secret": "private"}))
    identity = "skill_" + "a" * 32
    os.symlink(secret, root / f"{identity}.json")
    assert client.get(f"/api/workspace/skills/{identity}", headers=H).status_code == 404
    assert client.get("/api/workspace/skills", headers=H).json["data"] == []
    assert secret.exists()

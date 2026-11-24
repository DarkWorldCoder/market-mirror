"""Migrations on SQLite (always) and Postgres (when MM_TEST_POSTGRES_URL points at a throwaway database),
plus the one-time import of project files written by earlier versions."""
import json
import os
import shutil
import uuid

import pytest

from app import create_app
from app import db as dbmod
from app.api import setup
from app.db import Database, MigrationError, repo
from app.models.project import ProjectManager

TABLES = {"users", "workspaces", "memberships", "sessions", "invitations", "projects", "project_sources", "project_links",
          "chats", "chat_messages", "run_index", "pins", "preferences", "auth_attempts", "data_imports", "schema_migrations"}


def _tables(db):
    with db.transaction() as conn:
        if db.dialect == "sqlite":
            return {r["name"] for r in conn.all("SELECT name FROM sqlite_master WHERE type='table'")}
        return {r["table_name"] for r in conn.all("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}


def _exercise(db):
    assert db.migrate() == ["0001"]
    assert db.migrate() == []
    assert TABLES <= _tables(db)
    repo.ensure_local_workspace(db)
    repo.ensure_local_workspace(db)
    with db.transaction() as conn:
        user = repo.create_user(conn, "fixture@example.test", "Fixture", "$argon2id$fake")
        space = repo.create_workspace(conn, "Team", user["id"])
        saved = repo.save_chat(conn, space["id"], {"id": "c1", "messages": [{"role": "user", "content": "hi"}]}, None, user["id"])
        assert saved["messages"][0]["author"]["email"] == "fixture@example.test"
        with pytest.raises(repo.Conflict):
            repo.save_chat(conn, space["id"], {"id": "c1", "messages": []}, 7, user["id"])
        with pytest.raises(repo.Conflict):
            repo.create_user(conn, "fixture@example.test", "", "x")
    # Deleting a workspace removes its data through the foreign keys.
    with db.transaction() as conn:
        conn.execute("DELETE FROM workspaces WHERE id=?", (space["id"],))
        assert conn.scalar("SELECT count(*) AS n FROM chat_messages WHERE workspace_id=?", (space["id"],)) == 0
        assert conn.scalar("SELECT count(*) AS n FROM memberships WHERE workspace_id=?", (space["id"],)) == 0


def test_sqlite_migrates_once_and_is_owner_only(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/m.db")
    _exercise(db)
    assert os.stat(tmp_path / "m.db").st_mode & 0o777 == 0o600


def test_an_edited_applied_migration_stops_start_up(tmp_path, monkeypatch):
    folder = tmp_path / "migrations"
    shutil.copytree(dbmod.MIGRATIONS, folder)
    monkeypatch.setattr(dbmod, "MIGRATIONS", folder)
    db = Database(f"sqlite:///{tmp_path}/m.db")
    db.migrate()
    target = next(folder.glob("0001_*.sql"))
    target.write_text(target.read_text() + "\n-- edited\n")
    with pytest.raises(MigrationError):
        db.migrate()


def test_a_new_migration_applies_after_the_first(tmp_path, monkeypatch):
    folder = tmp_path / "migrations"
    shutil.copytree(dbmod.MIGRATIONS, folder)
    monkeypatch.setattr(dbmod, "MIGRATIONS", folder)
    db = Database(f"sqlite:///{tmp_path}/m.db")
    db.migrate()
    (folder / "0002_add_note.sql").write_text("ALTER TABLE workspaces ADD COLUMN note TEXT;")
    assert db.migrate() == ["0002"]
    assert set(db.applied()) == {"0001", "0002"}


@pytest.mark.skipif(not os.environ.get("MM_TEST_POSTGRES_URL"), reason="set MM_TEST_POSTGRES_URL to a throwaway Postgres")
def test_postgres_migrates_with_the_same_files():
    import psycopg
    base = os.environ["MM_TEST_POSTGRES_URL"]
    schema = "mm_test_" + uuid.uuid4().hex[:10]
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
    try:
        separator = "&" if "?" in base else "?"
        _exercise(Database(f"{base}{separator}options=-csearch_path%3D{schema}"))
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


def test_local_projects_import_from_workspace_json(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(setup, "SETUP_TOKEN", "migration-test")
    engine = ProjectManager.create_project("Old launch")
    legacy = {"id": engine.project_id, "name": "Old launch", "description": "From before", "instructions": "Cite",
              "chat_ids": ["chat-1"], "run_names": [], "preferred_model": "",
              "sources": [{"id": "src_0123456789ab", "name": "Brief", "text": "Evidence", "created_at": "2026-10-01T00:00:00+00:00"}],
              "created_at": "2026-10-01T00:00:00+00:00", "updated_at": "2026-10-02T00:00:00+00:00"}
    (tmp_path / "projects" / engine.project_id / "workspace.json").write_text(json.dumps(legacy))
    archived = ProjectManager.create_project("Gone")
    (tmp_path / "projects" / archived.project_id / "workspace.json").write_text(json.dumps({"name": "Gone", "archived": True}))
    cli_only = ProjectManager.create_project("Made by the CLI")
    app = create_app()
    client = app.test_client()
    listed = client.get("/api/workspace/projects", headers={"X-Setup-Token": "migration-test"}).json["data"]
    by_id = {p["id"]: p for p in listed}
    assert set(by_id) == {engine.project_id, cli_only.project_id}
    old = by_id[engine.project_id]
    assert old["description"] == "From before" and old["chat_ids"] == ["chat-1"]
    assert old["sources"][0]["id"] == "src_0123456789ab" and old["sources"][0]["text"] == "Evidence"
    assert old["created_at"].startswith("2026-10-01")
    # A second listing imports nothing twice, and the old file is left where it was.
    client.get("/api/workspace/projects", headers={"X-Setup-Token": "migration-test"})
    with dbmod.get_db().transaction() as conn:
        assert conn.scalar("SELECT count(*) AS n FROM projects") == 3
        assert conn.scalar("SELECT count(*) AS n FROM project_sources") == 1
    assert (tmp_path / "projects" / engine.project_id / "workspace.json").exists()

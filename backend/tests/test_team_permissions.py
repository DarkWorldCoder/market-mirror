"""Workspaces, roles, invitations and what each role may read or change. Generated fixture people only."""
import json
import time

import pytest

from app.db import get_db, repo
from test_accounts_auth import ORIGIN, REMOTE, TOKEN, fresh_password, headers, person, team_app  # noqa: F401


def invite(client, h, role="editor", email=None, days=7):
    response = client.post("/api/team/invitations", headers=h, json={"role": role, "email": email, "expires_in_days": days})
    assert response.status_code == 201, response.json
    return response.json["data"]["url"].split("#invite=")[1], response.json["data"]


def join(app, token, email=None):
    client, response, email, _ = person(app, email=email, invitation=token)
    return client, response, email


@pytest.fixture
def team(team_app):
    owner, signed, _, _ = person(team_app)
    oh = headers(signed)
    workspace = signed.json["data"]["workspace"]["id"]
    editor, er, _ = join(team_app, invite(owner, oh, "editor")[0])
    viewer, vr, _ = join(team_app, invite(owner, oh, "viewer")[0])
    return {"app": team_app, "ws": workspace, "owner": (owner, oh), "editor": (editor, headers(er, workspace)),
            "viewer": (viewer, headers(vr, workspace)), "ids": {"editor": er.json["data"]["account"]["id"],
                                                               "viewer": vr.json["data"]["account"]["id"]}}


def chat(chat_id="c1", text="hello"):
    return {"chat": {"id": chat_id, "title": text, "messages": [{"role": "user", "content": text}]}}


def test_invited_people_join_with_their_roles(team):
    owner, oh = team["owner"]
    members = owner.get("/api/team", headers=oh).json["data"]["members"]
    assert sorted(m["role"] for m in members) == ["editor", "owner", "viewer"]
    viewer, vh = team["viewer"]
    seen = viewer.get("/api/team", headers=vh).json["data"]
    assert seen["invitations"] == [] and len(seen["members"]) == 3


def test_invitation_tokens_are_single_use_hashed_and_revocable(team):
    owner, oh = team["owner"]
    token, row = invite(owner, oh)
    with get_db().transaction() as conn:
        stored = conn.one("SELECT token_hash FROM invitations WHERE id=?", (row["id"],))
    assert stored["token_hash"] == repo.token_hash(token)
    assert team["app"].test_client().get(f"/api/auth/invitations/{token}").json["data"]["role"] == "editor"
    first = join(team["app"], token)[1]
    assert first.status_code == 201
    assert join(team["app"], token)[1].status_code == 410
    token2, row2 = invite(owner, oh)
    assert owner.delete(f"/api/team/invitations/{row2['id']}", headers=oh).status_code == 200
    assert join(team["app"], token2)[1].status_code == 410


def test_invitation_bound_to_an_email_and_expiry(team):
    owner, oh = team["owner"]
    token, _ = invite(owner, oh, email="named@example.test")
    assert join(team["app"], token, email="other@example.test")[1].status_code == 403
    assert join(team["app"], token, email="named@example.test")[1].status_code == 201
    token, row = invite(owner, oh)
    with get_db().transaction() as conn:
        conn.execute("UPDATE invitations SET expires_at=? WHERE id=?", (repo.now_ms() - 1, row["id"]))
    assert join(team["app"], token)[1].status_code == 410


def test_only_owners_manage_people(team):
    editor, eh = team["editor"]
    viewer, vh = team["viewer"]
    for client, h in ((editor, eh), (viewer, vh)):
        assert client.post("/api/team/invitations", headers=h, json={"role": "viewer"}).status_code == 403
        assert client.patch(f"/api/team/members/{team['ids']['viewer']}", headers=h, json={"role": "owner"}).status_code == 403
        assert client.patch("/api/team/workspace", headers=h, json={"name": "Taken"}).status_code == 403
    owner, oh = team["owner"]
    assert owner.patch(f"/api/team/members/{team['ids']['viewer']}", headers=oh, json={"role": "editor"}).status_code == 200
    assert owner.patch(f"/api/team/members/{team['ids']['viewer']}", headers=oh, json={"role": "admin"}).status_code == 400


def test_the_last_owner_cannot_leave_or_be_demoted(team):
    owner, oh = team["owner"]
    me = owner.get("/api/auth/session").json["data"]["account"]["id"]
    assert owner.patch(f"/api/team/members/{me}", headers=oh, json={"role": "editor"}).status_code == 409
    assert owner.delete(f"/api/team/members/{me}", headers=oh).status_code == 409
    assert owner.patch(f"/api/team/members/{team['ids']['editor']}", headers=oh, json={"role": "owner"}).status_code == 200
    assert owner.patch(f"/api/team/members/{me}", headers=oh, json={"role": "editor"}).status_code == 200


def test_removed_members_lose_access_at_once(team):
    owner, oh = team["owner"]
    editor, eh = team["editor"]
    assert editor.get("/api/workspace/chats", headers=eh).status_code == 200
    assert owner.delete(f"/api/team/members/{team['ids']['editor']}", headers=oh).status_code == 200
    gone = editor.get("/api/workspace/chats", headers=eh)
    assert gone.status_code == 409 and gone.json["code"] == "workspace_changed"


def test_members_may_leave(team):
    viewer, vh = team["viewer"]
    assert viewer.delete(f"/api/team/members/{team['ids']['editor']}", headers=vh).status_code == 403
    assert viewer.delete(f"/api/team/members/{team['ids']['viewer']}", headers=vh).status_code == 200
    assert viewer.get("/api/workspace/chats", headers=vh).status_code == 409


def test_viewers_read_shared_chats_but_cannot_write_or_ask_the_model(team):
    owner, oh = team["owner"]
    viewer, vh = team["viewer"]
    assert owner.put("/api/workspace/chats/c1", headers=oh, json=chat()).status_code == 200
    listed = viewer.get("/api/workspace/chats", headers=vh).json["data"]["chats"]
    assert [c["id"] for c in listed] == ["c1"] and listed[0]["messages"][0]["author"]["email"]
    assert viewer.put("/api/workspace/chats/c1", headers=vh, json=chat(text="mine")).status_code == 403
    assert viewer.post("/api/workspace/chat", headers=vh, json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 403
    assert viewer.post("/api/workspace/projects", headers=vh, json={"name": "P"}).status_code == 403
    assert viewer.post("/api/workspace/chats/import", headers=vh, json={"source": "browser1", "chats": []}).status_code == 403


def test_editors_collaborate_with_revisions_and_delete_only_their_own(team):
    owner, oh = team["owner"]
    editor, eh = team["editor"]
    saved = owner.put("/api/workspace/chats/c1", headers=oh, json=chat()).json["data"]
    assert saved["revision"] == 1
    body = chat(text="edited")
    body["base_revision"] = 1
    assert editor.put("/api/workspace/chats/c1", headers=eh, json=body).json["data"]["revision"] == 2
    stale = owner.put("/api/workspace/chats/c1", headers=oh, json={**chat(text="late"), "base_revision": 1})
    assert stale.status_code == 409 and stale.json["data"]["current"]["revision"] == 2
    assert editor.delete("/api/workspace/chats/c1", headers=eh).status_code == 403
    assert editor.put("/api/workspace/chats/c2", headers=eh, json=chat("c2")).status_code == 200
    assert editor.delete("/api/workspace/chats/c2", headers=eh).status_code == 200
    assert owner.delete("/api/workspace/chats/c1", headers=oh).status_code == 200


def test_authorship_cannot_be_forged(team):
    owner, oh = team["owner"]
    editor, eh = team["editor"]
    owner.put("/api/workspace/chats/c1", headers=oh, json=chat())
    stored = owner.get("/api/workspace/chats/c1", headers=oh).json["data"]
    me = owner.get("/api/auth/session").json["data"]["account"]["id"]
    forged = {"chat": {**stored, "messages": [{**stored["messages"][0], "author": {"id": "someone"}},
                                              {"role": "user", "content": "new", "author": {"id": me}}]},
              "base_revision": stored["revision"]}
    result = editor.put("/api/workspace/chats/c1", headers=eh, json=forged).json["data"]
    assert result["messages"][0]["author"]["id"] == me
    assert result["messages"][1]["author"]["id"] == team["ids"]["editor"]


def test_workspaces_are_isolated(team, monkeypatch):
    owner, oh = team["owner"]
    owner.put("/api/workspace/chats/secret", headers=oh, json=chat("secret"))
    owner.post("/api/workspace/projects", headers=oh, json={"name": "Secret project"})
    monkeypatch.setenv("MM_SIGNUPS", "open")
    outsider, signed, _, _ = person(team["app"])
    xh = headers(signed)
    assert outsider.get("/api/workspace/chats", headers=xh).json["data"]["chats"] == []
    assert outsider.get("/api/workspace/projects", headers=xh).json["data"] == []
    assert outsider.get("/api/workspace/chats/secret", headers=xh).status_code == 404
    # Naming someone else's workspace in the header does not help.
    spoofed = {**xh, "X-MM-Workspace": team["ws"]}
    assert outsider.get("/api/workspace/chats", headers=spoofed).status_code == 409
    # Writing a chat with the same id in another workspace never touches the original.
    assert outsider.put("/api/workspace/chats/secret", headers=xh, json=chat("secret", "other")).status_code == 200
    assert owner.get("/api/workspace/chats/secret", headers=oh).json["data"]["title"] == "hello"


def test_people_switch_and_create_workspaces(team):
    owner, oh = team["owner"]
    created = owner.post("/api/auth/workspaces", headers=oh, json={"name": "Second"})
    assert created.status_code == 201
    data = created.json["data"]
    assert data["workspace"]["name"] == "Second" and len(data["workspaces"]) == 2
    back = owner.post("/api/auth/workspaces/select", headers=headers(data), json={"id": team["ws"]})
    assert back.json["data"]["workspace"]["id"] == team["ws"]
    assert owner.post("/api/auth/workspaces/select", headers=headers(data), json={"id": "ws_missing"}).status_code == 404


def _make_run(tmp_path, name):
    folder = tmp_path / "runs" / name
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps({"title": name}))


def test_runs_are_visible_only_through_the_workspace_index(team, tmp_path, monkeypatch):
    _make_run(tmp_path, "run-a")
    _make_run(tmp_path, "run-b")
    owner, oh = team["owner"]
    viewer, vh = team["viewer"]
    assert owner.get("/api/runs", headers=oh).json["data"]["runs"] == []
    assert owner.get("/api/runs/run-a", headers=oh).status_code == 404
    # An editor cannot claim a run folder they cannot already see.
    assert owner.post("/api/workspace/runs-index", headers=oh, json={"name": "run-a"}).status_code == 404
    local = team["app"].test_client()
    assert local.post("/api/workspace/runs-index", headers={"X-Setup-Token": TOKEN}, json={"name": "run-a"}).status_code == 201
    with get_db().transaction() as conn:
        repo.add_run(conn, team["ws"], "run-a", None)
    names = [r["name"] for r in viewer.get("/api/runs", headers=vh).json["data"]["runs"]]
    assert names == ["run-a"]
    assert viewer.get("/api/runs/run-a", headers=vh).status_code == 200
    assert viewer.get("/api/runs/run-b", headers=vh).status_code == 404
    assert viewer.get("/api/runs", headers=vh).json["data"]["root"] == ""
    # The chat endpoint refuses a run outside the workspace before calling any model.
    editor, eh = team["editor"]
    refused = editor.post("/api/workspace/chat", headers=eh,
                          json={"messages": [{"role": "user", "content": "hi"}], "run": "run-b"})
    assert refused.status_code == 400
    # A second workspace of the same editor can bring the run in.
    other = owner.post("/api/auth/workspaces", headers=oh, json={"name": "Second"}).json["data"]
    oh2 = headers(other)
    assert owner.post("/api/workspace/runs-index", headers=oh2, json={"name": "run-a"}).status_code == 201
    assert owner.post("/api/workspace/runs-index", headers=oh2, json={"name": "run-b"}).status_code == 404


def test_pins_are_per_person_and_limited_to_visible_runs(team):
    owner, oh = team["owner"]
    viewer, vh = team["viewer"]
    with get_db().transaction() as conn:
        repo.add_run(conn, team["ws"], "run-a", None)
    assert viewer.put("/api/workspace/pins", headers=vh, json={"pins": ["run-a", "hidden"]}).json["data"]["pins"] == ["run-a"]
    assert owner.get("/api/workspace/pins", headers=oh).json["data"]["pins"] == []


def test_preferences_and_onboarding_respect_roles(team):
    owner, oh = team["owner"]
    viewer, vh = team["viewer"]
    assert viewer.put("/api/workspace/preferences", headers=vh, json={"workspace": {"default_model": "m"}}).status_code == 403
    mine = viewer.put("/api/workspace/preferences", headers=vh, json={"user": {"theme": "dark"}}).json["data"]
    assert mine["user"] == {"theme": "dark"}
    assert owner.put("/api/workspace/preferences", headers=oh, json={"user": {"theme": "pink"}}).status_code == 400
    state = owner.put("/api/workspace/onboarding", headers=oh, json={"steps": {"workspace": True}}).json["data"]
    assert state["steps"] == {"workspace": True} and state["can_invite"] and not state["can_connect_model"]
    assert viewer.put("/api/workspace/onboarding", headers=vh, json={"steps": {"demo": True}}).status_code == 403


def test_one_time_chat_import(team):
    owner, oh = team["owner"]
    owner.put("/api/workspace/chats/kept", headers=oh, json=chat("kept", "server copy"))
    browser = [chat("kept", "browser copy")["chat"], chat("new1")["chat"],
               {"id": "new2", "title": "x", "messages": [{"role": "assistant", "content": "hi", "artifacts": [{"run": "r"}]}],
                "answerMode": "team", "updated": int(time.time() * 1000)}]
    first = owner.post("/api/workspace/chats/import", headers=oh, json={"source": "browser-abc123", "chats": browser})
    assert first.status_code == 201 and first.json["data"]["imported"] == 2 and first.json["data"]["skipped"] == 1
    again = owner.post("/api/workspace/chats/import", headers=oh, json={"source": "browser-abc123", "chats": browser})
    assert again.json["data"]["already_imported"] is True
    chats = {c["id"]: c for c in owner.get("/api/workspace/chats", headers=oh).json["data"]["chats"]}
    assert chats["kept"]["title"] == "server copy"
    assert chats["new2"]["answerMode"] == "team" and chats["new2"]["messages"][0]["artifacts"] == [{"run": "r"}]
    bad = owner.post("/api/workspace/chats/import", headers=oh, json={"source": "browser-zzz999",
                                                                      "chats": [{"id": "../x", "messages": []}]})
    assert bad.status_code == 400

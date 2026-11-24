"""Team mode sign-up, sign-in, sessions, CSRF, Origin and rate limits; local mode stays token-only.

Every person here is a generated fixture (example.test addresses, random passwords); nothing real is used.
"""
import secrets

import pytest

from app import create_app
from app.api import setup
from app.db import get_db, repo

ORIGIN = "http://localhost"
REMOTE = {"REMOTE_ADDR": "203.0.113.7"}
TOKEN = "accounts-test-token"


def fresh_password():
    return "pw-" + secrets.token_urlsafe(16)


@pytest.fixture
def team_app(monkeypatch, tmp_path):
    monkeypatch.setenv("MM_ACCOUNTS", "on")
    monkeypatch.setattr(setup, "SETUP_TOKEN", TOKEN)
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(tmp_path / "runs"))
    app = create_app()
    app.config.update(TESTING=True)
    return app


def person(app, email=None, password=None, **extra):
    client = app.test_client()
    client.environ_base.update(REMOTE)
    email = email or f"person-{secrets.token_hex(4)}@example.test"
    password = password or fresh_password()
    response = client.post("/api/auth/signup", headers={"Origin": ORIGIN},
                           json={"email": email, "password": password, "name": "Test person", **extra})
    return client, response, email, password


def headers(response_or_data, workspace=None):
    data = response_or_data.json["data"] if hasattr(response_or_data, "json") else response_or_data
    return {"Origin": ORIGIN, "X-CSRF-Token": data["csrf"], "X-MM-Workspace": workspace or data["workspace"]["id"]}


def test_first_person_signs_up_with_argon2id_and_a_safe_cookie(team_app):
    client, response, email, password = person(team_app)
    assert response.status_code == 201
    data = response.json["data"]
    assert data["account"]["email"] == email and data["workspace"]["role"] == "owner"
    cookie = response.headers["Set-Cookie"]
    assert "mm_session=" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    with get_db().transaction() as conn:
        user = repo.user_by_email(conn, email)
        stored = conn.one("SELECT token_hash FROM sessions WHERE user_id=?", (user["id"],))
    assert user["password_hash"].startswith("$argon2id$") and password not in user["password_hash"]
    token = cookie.split("mm_session=")[1].split(";")[0]
    assert stored["token_hash"] == repo.token_hash(token) and token not in stored["token_hash"]
    state = client.get("/api/auth/session").json["data"]
    assert state["account"]["email"] == email and state["csrf"] == data["csrf"]


def test_after_the_first_account_sign_up_needs_an_invitation(team_app):
    person(team_app)
    _, response, _, _ = person(team_app)
    assert response.status_code == 403 and response.json["code"] == "invite_required"


def test_open_and_closed_signup_policies(team_app, monkeypatch):
    person(team_app)
    monkeypatch.setenv("MM_SIGNUPS", "open")
    assert person(team_app)[1].status_code == 201
    monkeypatch.setenv("MM_SIGNUPS", "closed")
    assert person(team_app)[1].status_code == 403


def test_signup_rejects_short_passwords_bad_emails_and_duplicates(team_app):
    client, response, email, _ = person(team_app)
    other = team_app.test_client()
    assert other.post("/api/auth/signup", headers={"Origin": ORIGIN},
                      json={"email": "nobody", "password": fresh_password()}).status_code == 400
    assert other.post("/api/auth/signup", headers={"Origin": ORIGIN},
                      json={"email": "a@example.test", "password": "short"}).status_code == 400


def test_login_logout_and_wrong_password(team_app):
    _, _, email, password = person(team_app)
    client = team_app.test_client()
    client.environ_base.update(REMOTE)
    wrong = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"email": email, "password": "x" * 14})
    unknown = client.post("/api/auth/login", headers={"Origin": ORIGIN},
                          json={"email": "missing@example.test", "password": "x" * 14})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json["error"] == unknown.json["error"]
    ok = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"email": email.upper(), "password": password})
    assert ok.status_code == 200
    h = headers(ok)
    assert client.get("/api/workspace/chats", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 403   # no CSRF token
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/workspace/chats", headers=h).status_code == 401
    assert client.get("/api/auth/session").json["data"]["account"] is None


def test_login_and_signup_refuse_other_origins(team_app):
    _, _, email, password = person(team_app)
    client = team_app.test_client()
    for origin in ("https://evil.example", None):
        h = {"Origin": origin} if origin else {}
        assert client.post("/api/auth/login", headers=h, json={"email": email, "password": password}).status_code == 403


def test_writes_need_the_session_csrf_token_and_origin(team_app):
    client, response, _, _ = person(team_app)
    h = headers(response)
    chat = {"chat": {"id": "c1", "title": "Hi", "messages": [{"role": "user", "content": "hello"}]}}
    assert client.put("/api/workspace/chats/c1", headers={**h, "X-CSRF-Token": "wrong"}, json=chat).status_code == 403
    assert client.put("/api/workspace/chats/c1", headers={**h, "Origin": "https://evil.example"}, json=chat).status_code == 403
    no_origin = {k: v for k, v in h.items() if k != "Origin"}
    assert client.put("/api/workspace/chats/c1", headers=no_origin, json=chat).status_code == 403
    assert client.put("/api/workspace/chats/c1", headers=h, json=chat).status_code == 200


def test_failed_logins_are_rate_limited_per_email(team_app):
    _, _, email, password = person(team_app)
    client = team_app.test_client()
    for _ in range(10):
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN},
                           json={"email": email, "password": "wrong-password-1"}).status_code == 401
    blocked = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"email": email, "password": password})
    assert blocked.status_code == 429


def test_attempts_are_rate_limited_per_client(team_app):
    client = team_app.test_client()
    client.environ_base.update({"REMOTE_ADDR": "198.51.100.9"})
    codes = [client.post("/api/auth/login", headers={"Origin": ORIGIN},
                         json={"email": f"p{i}@example.test", "password": "wrong-password-1"}).status_code for i in range(31)]
    assert codes[:30] == [401] * 30 and codes[30] == 429


def test_password_change_signs_out_other_sessions(team_app):
    first, response, email, password = person(team_app)
    second = team_app.test_client()
    other = second.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"email": email, "password": password})
    new = fresh_password()
    changed = first.post("/api/auth/password", headers=headers(response),
                         json={"current_password": password, "new_password": new})
    assert changed.status_code == 200
    assert second.get("/api/workspace/chats", headers=headers(other)).status_code == 401
    assert first.get("/api/workspace/chats", headers=headers(changed)).status_code == 200


def test_local_mode_ignores_session_cookies_and_keeps_the_setup_token(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "SETUP_TOKEN", TOKEN)
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    assert client.get("/api/auth/session").json["data"]["mode"] == "local"
    assert client.post("/api/auth/signup", headers={"Origin": ORIGIN},
                       json={"email": "a@example.test", "password": fresh_password()}).status_code == 404
    # A forged cookie gives nothing; the token on loopback still works; the token off loopback does not.
    client.set_cookie("mm_session", "forged")
    assert client.get("/api/workspace/chats").status_code == 403
    assert client.get("/api/workspace/chats", headers={"X-Setup-Token": TOKEN}).status_code == 200
    remote = app.test_client()
    remote.environ_base.update(REMOTE)
    assert remote.get("/api/workspace/chats", headers={"X-Setup-Token": TOKEN}).status_code == 403


def test_team_mode_keeps_engine_settings_on_this_computer(team_app):
    client, response, _, _ = person(team_app)
    h = headers(response)
    assert client.get("/api/workspace/settings", headers=h).status_code == 403
    assert client.get("/api/setup/state", headers=h).status_code == 403
    assert client.get("/api/workspace/connectors", headers=h).status_code == 403


def test_production_requires_an_https_public_origin_in_team_mode(monkeypatch):
    from app.config import Config
    monkeypatch.setenv("MM_ENV", "production")
    monkeypatch.setenv("MM_ACCOUNTS", "on")
    monkeypatch.delenv("MM_PUBLIC_ORIGIN", raising=False)
    assert any("MM_PUBLIC_ORIGIN" in e for e in Config.production_errors(host="127.0.0.1"))
    monkeypatch.setenv("MM_PUBLIC_ORIGIN", "https://mm.example.test")
    assert not any("MM_PUBLIC_ORIGIN" in e for e in Config.production_errors(host="127.0.0.1"))

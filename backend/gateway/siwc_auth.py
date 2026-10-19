"""Local Sign in with ChatGPT OAuth for eligible open-source app users.

Implements the documented dynamic client registration, PKCE loopback callback,
ID-token validation, protected token storage, refresh, and scope/model check.
Never reads Codex CLI credentials or ChatGPT web endpoints.
"""

from __future__ import annotations

import base64
import argparse
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
import requests

AUTH = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DEFAULT_PATH = os.path.expanduser("~/.config/market-mirror/siwc.json")
_LOCK = threading.RLock()


class SignInError(RuntimeError):
    pass


def _read(path: str = DEFAULT_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(data: dict, path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), mode=0o700, exist_ok=True)
    temp = path + ".tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def status(path: str = DEFAULT_PATH) -> dict:
    data = _read(path)
    return {"registered": bool(data.get("client_id")), "eligible_scope": "chatgpt.tokens.use.direct" in data.get("scopes", []),
            "expires_at": data.get("expires_at"), "email": data.get("email"),
            "model": data.get("model"), "needs_login": not bool(data.get("refresh_token"))}


def _verify_id_token(token: str, client_id: str, nonce: str) -> dict:
    discovery = requests.get(AUTH + "/.well-known/openid-configuration", timeout=20)
    discovery.raise_for_status()
    jwks_uri = discovery.json()["jwks_uri"]
    key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256"], audience=client_id, issuer=AUTH,
                        options={"require": ["exp", "iss", "aud", "sub"]})
    if claims.get("nonce") != nonce:
        raise SignInError("ID-token nonce mismatch")
    return claims


def login(path: str = DEFAULT_PATH, timeout_s: int = 300, open_browser: bool = True) -> dict:
    existing = _read(path)
    host_id = existing.get("ext_agent_host_id") or f"urn:uuid:{uuid.uuid4()}"
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path != "/auth/callback":
                self.send_error(404)
                return
            result.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items() if v})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"MarketMirror sign-in received. Return to the terminal.")

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Callback)
    server.timeout = min(5, timeout_s)
    redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
    requested_id = existing.get("client_id") or "dynamic_agent_client"
    params = {"client_id": requested_id, "ext_agent_host_id": host_id, "response_type": "code",
              "redirect_uri": redirect, "scope": SCOPES, "resource": RESOURCE, "state": state,
              "nonce": nonce, "code_challenge_method": "S256", "code_challenge": challenge}
    if requested_id == "dynamic_agent_client":
        params["agent_name_hint"] = "MarketMirror"
    elif existing.get("email"):
        params["login_hint"] = existing["email"]
    url = AUTH + "/api/accounts/authorize?" + urlencode(params)
    if open_browser:
        webbrowser.open(url)
    else:
        print("Open this authorization URL in a local browser:\n" + url, flush=True)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not result:
        server.handle_request()
    server.server_close()
    if not result:
        raise SignInError("sign-in callback timed out")
    if not secrets.compare_digest(result.get("state", ""), state):
        raise SignInError("OAuth state mismatch")
    if result.get("error"):
        raise SignInError("authorization denied or unavailable: " + result["error"])
    issued = result.get("client_id") or (requested_id if requested_id != "dynamic_agent_client" else "")
    if not issued or (requested_id != "dynamic_agent_client" and issued != requested_id):
        raise SignInError("issued client ID missing or changed")
    response = requests.post(AUTH + "/api/accounts/oauth/token", data={"grant_type": "authorization_code",
        "client_id": issued, "code": result.get("code"), "code_verifier": verifier,
        "redirect_uri": redirect, "resource": RESOURCE}, timeout=30)
    if not response.ok:
        raise SignInError(f"token exchange failed (HTTP {response.status_code})")
    token = response.json()
    claims = _verify_id_token(token["id_token"], issued, nonce)
    if existing.get("subject") and existing["subject"] != claims["sub"]:
        raise SignInError("returning ChatGPT account changed")
    scopes = token.get("scope", "").split()
    if "chatgpt.tokens.use.direct" not in scopes:
        raise SignInError("this account is not authorized for ChatGPT plan inference")
    record = {"client_id": issued, "ext_agent_host_id": host_id, "subject": claims["sub"],
              "email": claims.get("email"), "id_token": token["id_token"],
              "access_token": token["access_token"], "refresh_token": token.get("refresh_token"),
              "scopes": scopes, "expires_at": time.time() + int(token.get("expires_in", 3600))}
    models = requests.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + record["access_token"]}, timeout=30)
    if not models.ok:
        raise SignInError(f"eligibility/model check failed (HTTP {models.status_code})")
    choices = [m for m in models.json().get("models", []) if m.get("visibility") == "list"]
    if not choices:
        raise SignInError("no eligible models available for this account")
    record["model"] = (existing.get("model") if any(m.get("slug") == existing.get("model") for m in choices)
                       else choices[0]["slug"])
    _write(record, path)
    return {"eligible": True, "email": record["email"], "model": record["model"], "models": [m.get("slug") for m in choices]}


def access_token(path: str = DEFAULT_PATH) -> tuple[str, str]:
    with _LOCK:
        data = _read(path)
        if "chatgpt.tokens.use.direct" not in data.get("scopes", []) or not data.get("refresh_token"):
            raise SignInError("Continue with ChatGPT setup is required or account is ineligible")
        if data.get("expires_at", 0) > time.time() + 60:
            return data["access_token"], data["model"]
        response = requests.post(AUTH + "/api/accounts/oauth/token", data={"grant_type": "refresh_token",
            "client_id": data["client_id"], "refresh_token": data["refresh_token"], "resource": RESOURCE}, timeout=30)
        if not response.ok:
            raise SignInError(f"ChatGPT session expired; sign in again (HTTP {response.status_code})")
        token = response.json()
        data.update({"access_token": token["access_token"], "refresh_token": token.get("refresh_token", data["refresh_token"]),
                     "scopes": token.get("scope", "").split() or data["scopes"],
                     "expires_at": time.time() + int(token.get("expires_in", 3600))})
        if "chatgpt.tokens.use.direct" not in data["scopes"]:
            raise SignInError("ChatGPT plan inference permission was revoked")
        _write(data, path)
        return data["access_token"], data["model"]


def main() -> int:
    parser = argparse.ArgumentParser(description="MarketMirror Continue with ChatGPT setup")
    parser.add_argument("action", choices=["login", "status"])
    parser.add_argument("--no-open", action="store_true", help="print authorization URL instead of opening browser")
    parser.add_argument("--path", default=DEFAULT_PATH)
    args = parser.parse_args()
    try:
        out = login(args.path, open_browser=not args.no_open) if args.action == "login" else status(args.path)
        print(json.dumps(out))
        return 0
    except (SignInError, requests.RequestException, KeyError, jwt.PyJWTError) as e:
        print(json.dumps({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

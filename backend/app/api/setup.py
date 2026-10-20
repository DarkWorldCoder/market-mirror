"""
setup.py - provider settings in the browser: choose how the simulated people are answered (a local login through
the gateway, or an API key), enter keys, start and stop gateways, test the connection and apply the change to the
running backend.

Only requests from this computer are served. Every change needs the setup token, which the backend writes to
backend/logs/setup.token (owner-only) and `./mm setup` passes in the page URL; a page on another site cannot read
it, so it cannot change keys or start processes. Keys are written to .env (owner-only) and never sent back.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, Response, jsonify, request

from ..config import Config
from ..utils.model_pool import API_PROVIDERS, PROVIDER_ALIASES, provider_api_key

setup_bp = Blueprint("setup", __name__)

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
LOGS = BACKEND / "logs"
TOKEN_FILE = LOGS / "setup.token"
# keys the page may store (masked, owner-only): one per API provider, plus TYPESAFE_API_KEY for scoring integrations
STORED_KEY_NAMES = tuple(dict.fromkeys(("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                                        *(s["key_env"] for s in API_PROVIDERS.values()), "TYPESAFE_API_KEY")))
KEY_NAMES = STORED_KEY_NAMES + ("LLM_API_KEY",)
GATEWAY_BACKENDS = {
    "claude": {"label": "Claude Code login", "bins": ["claude"], "models": ["sonnet", "haiku", "opus"], "default": "sonnet", "port": 5055},
    "codex": {"label": "Codex login (ChatGPT account)", "bins": ["codex", "/usr/lib/chatgpt/resources/codex",
                                                                   str(Path.home() / ".codex/plugins/.plugin-appserver/codex")],
              "models": [], "default": "", "port": 5056},
    "antigravity": {"label": "Antigravity login (Gemini models)", "bins": ["agy", str(Path.home() / ".local/bin/agy")],
                    "models": ["gemini-4-argon-medium", "gemini-4-argon-low", "gemini-4-argon-high", "gemini-3.8-flash-low",
                               "gemini-3.8-flash-medium", "gemini-3.8-flash-high"], "default": "gemini-4-argon-medium", "port": 5057},
}
GATEWAY_KEYS = ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_API_KEY", "LLM_GATEWAY", "MARKET_MIRROR_PROVIDER")


def _token() -> str:
    LOGS.mkdir(parents=True, exist_ok=True)
    try:
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(t)
    return t


SETUP_TOKEN = _token()


def _loopback() -> bool:
    try:
        return ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False


def _guard(write: bool = True):
    if not _loopback():
        return jsonify({"success": False, "error": "settings are only available on this computer"}), 403
    given = request.headers.get("X-Setup-Token", "")
    if not hmac.compare_digest(given, SETUP_TOKEN):
        return jsonify({"success": False, "error": "open the settings page with ./mm setup"}), 403
    if write:
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify({"success": False, "error": "cross-site request refused"}), 403
    return None


# --------------------------------------------------------------------------
# .env
# --------------------------------------------------------------------------

def _env_path() -> Path:
    return ROOT / ".env"


def _read_env() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for line in _env_path().read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() and not name.strip().startswith("#"):
                raw = value.strip()
                try:
                    out[name.strip()] = json.loads(raw) if raw.startswith('"') else raw.strip("'")
                except ValueError:
                    out[name.strip()] = raw
    except FileNotFoundError:
        pass
    return out


def _write_env(values: Dict[str, Optional[str]]) -> None:
    """Set (or remove, with None) these keys in .env atomically, owner-only."""
    for v in values.values():
        if v is not None and any(c in v for c in ("\r", "\n", "\x00")):
            raise ValueError("values must be a single line")
    path = _env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if ln.partition("=")[0].strip() not in values]
    lines += [f"{k}={json.dumps(v)}" for k, v in values.items() if v is not None]
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=str(ROOT))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _mask(v: Optional[str]) -> Optional[str]:
    if not v or v in ("your_api_key_here", "local"):
        return None
    return f"set, ends in …{v[-4:]}" if len(v) > 12 else "set"


def apply_to_backend() -> Dict[str, Any]:
    """Reload the provider settings from .env into this running backend (new tasks use them)."""
    env = _read_env()
    for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_API_KEY", "LLM_POOL", "LLM_GATEWAY") + STORED_KEY_NAMES:
        if env.get(k):
            os.environ[k] = env[k]
        elif k in ("LLM_POOL", "LLM_GATEWAY"):
            os.environ.pop(k, None)
    prov = (env.get("LLM_PROVIDER") or "claude").lower()
    hosted = PROVIDER_ALIASES.get(prov)
    Config.LLM_PROVIDER = prov
    Config.LLM_POOL = env.get("LLM_POOL", "")
    Config.LLM_API_KEY = (env.get("LLM_API_KEY") or (env.get("ANTHROPIC_API_KEY") if prov == "claude" else None)
                          or (env.get("GEMINI_API_KEY") if prov == "gemini" else None)
                          or (env.get("OPENAI_API_KEY") if prov == "openai" else None)
                          or (provider_api_key(hosted, {**os.environ, **env}) if hosted in API_PROVIDERS else None)
                          or Config.LLM_API_KEY)
    if env.get("LLM_BASE_URL"):
        Config.LLM_BASE_URL = env["LLM_BASE_URL"]
    if env.get("LLM_MODEL_NAME"):
        Config.LLM_MODEL_NAME = env["LLM_MODEL_NAME"]
    for name in ("_POOL", "_pool", "_POOL_CACHE"):
        if hasattr(Config, name):
            setattr(Config, name, None)
    return {"provider": Config.LLM_PROVIDER, "model": Config.LLM_MODEL_NAME, "base_url": Config.LLM_BASE_URL}


# --------------------------------------------------------------------------
# Gateways
# --------------------------------------------------------------------------

def _find_bin(backend: str) -> Optional[str]:
    for b in GATEWAY_BACKENDS[backend]["bins"]:
        p = shutil.which(b) if "/" not in b else (b if os.access(b, os.X_OK) else None)
        if p:
            return p
    return None


def _health(port: int) -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/health", timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - not running
        return None


def _pid_file(port: int) -> Path:
    return LOGS / f"gateway-{int(port)}.pid"


def gateways() -> List[Dict[str, Any]]:
    out = []
    ports = sorted({spec["port"] for spec in GATEWAY_BACKENDS.values()} |
                   {int(p.stem.split("-")[1]) for p in LOGS.glob("gateway-*.pid") if p.stem.split("-")[1].isdigit()})
    for port in ports:
        h = _health(port)
        if h:
            out.append({"port": port, "backend": h.get("backend"), "model": h.get("model"), "available": h.get("available"),
                        "paused": h.get("paused"), "paused_until": h.get("paused_until"), "requests": h.get("requests")})
    return out


def start_gateway(backend: str, port: int, model: str = "", workers: int = 8) -> Dict[str, Any]:
    if backend not in GATEWAY_BACKENDS:
        raise ValueError(f"unknown login: {backend}")
    if not 1024 < int(port) < 65536:
        raise ValueError("port must be between 1025 and 65535")
    h = _health(port)
    if h:
        if h.get("backend") == backend:
            return {"port": port, "already_running": True, "backend": backend, "model": h.get("model")}
        raise ValueError(f"port {port} is already used by the {h.get('backend')} gateway; stop it or pick another port")
    binary = _find_bin(backend)
    if not binary:
        raise ValueError(f"{GATEWAY_BACKENDS[backend]['label']}: the command-line tool is not installed on this computer")
    tok_file = LOGS / f"gateway-{int(port)}.token"
    if not tok_file.exists():
        fd = os.open(tok_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(32))
    cmd = [sys.executable, str(BACKEND / "gateway" / "local_gateway.py"), "--backend", backend, "--port", str(int(port)),
           "--workers", str(max(1, min(int(workers), 16))), "--timeout", "300", "--auth-token-file", str(tok_file),
           "--binary", binary]
    if model:
        cmd += ["--model", model]
    log = open(LOGS / f"gateway-{int(port)}.out", "ab")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(BACKEND))
    _pid_file(port).write_text(str(proc.pid), encoding="utf-8")
    for _ in range(40):
        time.sleep(0.25)
        if _health(port):
            return {"port": port, "started": True, "backend": backend, "model": model}
        if proc.poll() is not None:
            break
    tail = (LOGS / f"gateway-{int(port)}.out").read_text(encoding="utf-8", errors="replace")[-400:]
    raise RuntimeError(f"the gateway did not start: {tail.strip().splitlines()[-1] if tail.strip() else 'no output'}")


def stop_gateway(port: int) -> Dict[str, Any]:
    pf = _pid_file(port)
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        raise ValueError(f"no gateway started from settings on port {port}")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    pf.unlink(missing_ok=True)
    return {"port": port, "stopped": True}


def use_gateway(backend: str, port: int, model: str) -> Dict[str, Any]:
    tok = (LOGS / f"gateway-{int(port)}.token").read_text(encoding="utf-8").strip()
    _write_env({"LLM_PROVIDER": "openai", "LLM_BASE_URL": f"http://127.0.0.1:{int(port)}/v1",
                "LLM_MODEL_NAME": model or GATEWAY_BACKENDS[backend]["default"] or backend, "LLM_API_KEY": tok,
                "LLM_GATEWAY": backend, "MARKET_MIRROR_PROVIDER": backend, "LLM_POOL": None})
    return apply_to_backend()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@setup_bp.route("/setup", methods=["GET"])
def setup_page():
    if not _loopback():
        return Response("Settings are only available on this computer.", status=403, mimetype="text/plain")
    return Response(SETUP_HTML, mimetype="text/html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                                              "X-Frame-Options": "DENY"})


@setup_bp.route("/api/setup/state", methods=["GET"])
def setup_state():
    bad = _guard(write=False)
    if bad:
        return bad
    sys.path.insert(0, str(BACKEND / "claude_cli"))
    import providers  # noqa: E402
    env = _read_env()
    catalog = [{"id": k, "label": v["label"], "key_required": v.get("key_required", False), "base_url": v.get("base_url", ""),
                "key_env": v.get("key_env", ""), "key_url": v.get("key_url", ""), "default_model": v.get("default_model", ""),
                "note": v.get("note", "")}
               for k, v in providers.CATALOG.items() if not v.get("gateway")]
    logins = [{"id": k, "label": v["label"], "installed": bool(_find_bin(k)), "models": v["models"], "default_model": v["default"],
               "port": v["port"]} for k, v in GATEWAY_BACKENDS.items()]
    return jsonify({"success": True, "data": {
        "current": {**providers.status(ROOT), "gateway": env.get("LLM_GATEWAY") or None,
                    "running": {"provider": Config.LLM_PROVIDER, "model": Config.LLM_MODEL_NAME}},
        "keys": {k: _mask(env.get(k) or os.environ.get(k)) for k in STORED_KEY_NAMES},
        "api_providers": catalog, "logins": logins, "gateways": gateways()}})


@setup_bp.route("/api/setup/key", methods=["POST"])
def setup_key():
    bad = _guard()
    if bad:
        return bad
    data = request.get_json(silent=True) or {}
    name, value = str(data.get("name") or ""), str(data.get("value") or "").strip()
    if name not in STORED_KEY_NAMES:
        return jsonify({"success": False, "error": f"key name must be one of {', '.join(STORED_KEY_NAMES)}"}), 400
    if len(value) < 16 or any(c.isspace() for c in value):
        return jsonify({"success": False, "error": "that does not look like an API key"}), 400
    _write_env({name: value})
    return jsonify({"success": True, "data": {"name": name, "stored": _mask(value)}})


@setup_bp.route("/api/setup/provider", methods=["POST"])
def setup_provider():
    """{kind: "api", provider, model, base_url?} uses a stored key; {kind: "login", backend, model, port} starts the
    gateway if needed and points the backend at it."""
    bad = _guard()
    if bad:
        return bad
    data = request.get_json(silent=True) or {}
    try:
        if data.get("kind") == "login":
            backend = str(data.get("backend") or "")
            spec = GATEWAY_BACKENDS.get(backend)
            if not spec:
                raise ValueError("choose Claude Code, Codex or Antigravity")
            port = int(data.get("port") or spec["port"])
            model = str(data.get("model") or spec["default"])
            started = start_gateway(backend, port, model)
            applied = use_gateway(backend, port, model)
            return jsonify({"success": True, "data": {"gateway": started, "applied": applied}})
        sys.path.insert(0, str(BACKEND / "claude_cli"))
        import providers  # noqa: E402
        prov = str(data.get("provider") or "")
        if prov not in providers.CATALOG or providers.CATALOG[prov].get("gateway"):
            raise ValueError("choose an API provider")
        spec = providers.CATALOG[prov]
        env = _read_env()
        key = next((env.get(n) or os.environ.get(n) for n in (spec.get("key_env"), *spec.get("alt_key_envs", ()))
                    if n and (env.get(n) or os.environ.get(n))), "") or str(data.get("key") or "").strip()
        model = str(data.get("model") or "").strip() or (spec.get("default_model", "") if prov in providers.API_GUIDES else "")
        providers.write_config(ROOT, prov, model, str(data.get("base_url") or ""), key or "")
        _write_env({"LLM_GATEWAY": None})
        return jsonify({"success": True, "data": {"applied": apply_to_backend()}})
    except (ValueError, KeyError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502


@setup_bp.route("/api/setup/gateway", methods=["POST"])
def setup_gateway():
    bad = _guard()
    if bad:
        return bad
    data = request.get_json(silent=True) or {}
    try:
        if data.get("action") == "stop":
            return jsonify({"success": True, "data": stop_gateway(int(data.get("port")))})
        backend = str(data.get("backend") or "")
        spec = GATEWAY_BACKENDS.get(backend)
        if not spec:
            raise ValueError("choose Claude Code, Codex or Antigravity")
        return jsonify({"success": True, "data": start_gateway(backend, int(data.get("port") or spec["port"]), str(data.get("model") or spec["default"]))})
    except (ValueError, TypeError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502


@setup_bp.route("/api/setup/test", methods=["POST"])
def setup_test():
    """One tiny call with the provider the backend is using now."""
    bad = _guard()
    if bad:
        return bad
    from openai import OpenAI
    t0 = time.time()
    try:
        client = OpenAI(api_key=Config.LLM_API_KEY or "missing", base_url=Config.LLM_BASE_URL, max_retries=0, timeout=180)
        resp = client.chat.completions.create(model=Config.LLM_MODEL_NAME, max_tokens=20, temperature=0,
                                              messages=[{"role": "user", "content": "Reply with the single word: ready"}])
        text = (resp.choices[0].message.content or "").strip()
        return jsonify({"success": True, "data": {"ok": True, "reply": text[:40], "seconds": round(time.time() - t0, 1),
                                                  "provider": Config.LLM_PROVIDER, "model": getattr(resp, "model", Config.LLM_MODEL_NAME)}})
    except Exception as e:  # noqa: BLE001 - reported to the page without secrets
        msg = str(e)
        for k in KEY_NAMES:
            v = os.environ.get(k)
            if v:
                msg = msg.replace(v, "…")
        return jsonify({"success": True, "data": {"ok": False, "error": msg[:300], "seconds": round(time.time() - t0, 1)}})


SETUP_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Provider settings · MarketMirror</title><style>
:root{color-scheme:light;--bg:#eeeeea;--card:#fff;--sunk:#f6f6f3;--ink:#111;--ink2:#3d3d3a;--mut:#6b6b66;--line:#dcdbd5;--acc:#f3d64b;--accink:#2b2005;--ok:#cfefd9;--okink:#0f3d22;--bad:#fde6e6;--badink:#9e2b2a}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0d0d0c;--card:#171716;--sunk:#1f1f1d;--ink:#f2f2ee;--ink2:#c9c9c2;--mut:#8f8f88;--line:#2a2a28;--ok:#183b25;--okink:#cfefd9;--bad:#3f1d1d;--badink:#f2a5a5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 24px 64px}
.eyebrow{color:var(--mut);font-size:13px;margin:0 0 8px}h1{font-size:clamp(2rem,4vw,3rem);font-weight:500;letter-spacing:-.045em;text-transform:uppercase;margin:0 0 20px;line-height:1}
h2{font-size:1.25rem;font-weight:500;letter-spacing:-.02em;margin:30px 0 12px}
.now{background:#121212;color:#f2f2ee;border-radius:24px;padding:18px 22px;display:flex;flex-wrap:wrap;gap:12px 28px;align-items:center}
.now b{font-size:1.15rem;font-weight:500}.now span{color:#9a9a93;font-size:12.5px;display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.card{background:var(--card);border-radius:22px;padding:18px 20px}
.card h3{margin:0 0 4px;font-size:1rem;font-weight:600}.card p{margin:0 0 12px;color:var(--ink2);font-size:13px}
label{display:block;font-size:12px;color:var(--mut);margin:10px 0 4px}
input,select{width:100%;font:inherit;padding:9px 12px;border-radius:12px;border:1px solid var(--line);background:var(--sunk);color:var(--ink)}
.row{display:flex;gap:8px;align-items:end}.row>*{flex:1}
button{font:inherit;font-weight:500;border:0;border-radius:999px;padding:9px 16px;cursor:pointer;background:var(--ink);color:var(--card);margin-top:12px}
button.ghost{background:var(--sunk);color:var(--ink)}button:disabled{opacity:.5;cursor:default}
.pill{display:inline-block;font-size:11.5px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--sunk);color:var(--ink2)}
.pill.ok{background:var(--ok);color:var(--okink)}.pill.no{background:var(--bad);color:var(--badink)}.pill.acc{background:var(--acc);color:var(--accink)}
#msg{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);max-width:min(92vw,640px);background:#121212;color:#f2f2ee;padding:10px 18px;border-radius:999px;display:none;font-size:13px}
.gw{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line)}
.gw:first-child{border-top:0}.small{font-size:12px;color:var(--mut)}
.locked{background:var(--card);border-radius:22px;padding:24px}
</style></head><body><div class="wrap">
<p class="eyebrow">MarketMirror · runs on this computer only</p><h1>Provider settings</h1>
<div id="locked" class="locked" hidden><h3>Open this page with ./mm setup</h3><p>For safety the settings need the one-time link that <code>./mm setup</code> opens.</p></div>
<div id="app" hidden>
<div class="now" id="now"></div>
<h2>Use a login you already have (no API key)</h2>
<p class="small">Each login runs through a small local gateway. Every simulated person is one call, so a login's usage limit decides how fast large runs go; runs pause and resume when it is reached.</p>
<div class="grid" id="logins"></div>
<h2>Or use an API key</h2>
<div class="grid">
 <div class="card"><h3>Your keys</h3><p>Stored in .env on this computer (owner-only). They are never shown again.</p>
  <label>Which key</label><select id="kname"></select>
  <label>Key</label><input id="kval" type="password" autocomplete="off" placeholder="paste the key">
  <button id="ksave">Save key</button><div id="kstate" class="small" style="margin-top:10px"></div></div>
 <div class="card"><h3>Answer with an API</h3><p>Uses the saved key for that provider.</p>
  <label>Provider</label><select id="aprov"></select>
  <label>Model</label><input id="amodel" placeholder="for example claude-sonnet-5-5, gpt-5.4-mini, gemini-3.8-flash">
  <label>Endpoint (only for Qwen or another OpenAI-compatible server)</label><input id="aurl" placeholder="https://...">
  <button id="ause">Use this provider</button></div>
</div>
<h2>Gateways running</h2><div class="card" id="gws"></div>
<h2>Check</h2><div class="card"><p>Sends one tiny request with the provider the backend uses now.</p><button id="test">Test the connection</button><div id="tres" class="small" style="margin-top:10px"></div></div>
</div></div><div id="msg"></div>
<script>
var T=new URLSearchParams(location.hash.slice(1)).get('t')||new URLSearchParams(location.search).get('t')||'';
if(location.search.indexOf('t=')>=0){history.replaceState(null,'',location.pathname+'#t='+encodeURIComponent(T));}
function $(i){return document.getElementById(i);}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function msg(t){var m=$('msg');m.textContent=t;m.style.display='block';clearTimeout(msg.t);msg.t=setTimeout(function(){m.style.display='none';},5000);}
function api(path,body){return fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Setup-Token':T},body:body?JSON.stringify(body):undefined})
 .then(function(r){return r.json();}).then(function(j){if(!j.success)throw new Error(j.error||'failed');return j.data;});}
function busy(b,on,label){b.disabled=on;if(label)b.textContent=label;}
function render(d){
 var c=d.current;$('now').innerHTML='<div><span>Answering now</span><b>'+esc(c.gateway?(c.gateway+' login'):(c.provider||'not set'))+'</b></div><div><span>Model</span><b>'+esc(c.running.model||'–')+'</b></div>'+
  '<div><span>Credential</span><b>'+(c.credential_configured?'set':'missing')+'</b></div>'+(c.base_url?'<div><span>Endpoint</span><b>'+esc(c.base_url)+'</b></div>':'');
 $('logins').innerHTML=d.logins.map(function(l){var running=d.gateways.filter(function(g){return g.backend===l.id;})[0];
  var opts=(l.models.length?l.models:['']).map(function(m){return '<option value="'+esc(m)+'"'+(m===l.default_model?' selected':'')+'>'+esc(m||'the login\'s default model')+'</option>';}).join('');
  return '<div class="card"><h3>'+esc(l.label)+'</h3><p>'+(l.installed?'<span class="pill ok">installed</span>':'<span class="pill no">not installed</span>')+
   (running?' <span class="pill acc">running on '+running.port+(running.paused?' · paused until '+esc(running.paused_until):'')+'</span>':'')+'</p>'+
   '<div class="row"><div><label>Model</label><select id="m_'+l.id+'">'+opts+'</select></div><div style="flex:0 0 96px"><label>Port</label><input id="p_'+l.id+'" value="'+(running?running.port:l.port)+'"></div></div>'+
   '<button data-use="'+l.id+'"'+(l.installed?'':' disabled')+'>Start and use</button> <button class="ghost" data-start="'+l.id+'"'+(l.installed?'':' disabled')+'>Start only</button></div>';}).join('');
 var prev=$('aprov').value,kprev=$('kname').value;
 $('aprov').innerHTML=d.api_providers.map(function(p){return '<option value="'+esc(p.id)+'">'+esc(p.label)+'</option>';}).join('');
 if(prev)$('aprov').value=prev;
 $('aprov').onchange=function(){var p=d.api_providers.filter(function(x){return x.id===$('aprov').value;})[0]||{};
  $('amodel').placeholder=p.default_model?('default '+p.default_model):'model identifier from your provider';
  $('aurl').placeholder=p.note||p.base_url||'https://...';
  if(p.key_env&&d.keys.hasOwnProperty(p.key_env))$('kname').value=p.key_env;};
 $('kname').innerHTML=Object.keys(d.keys).map(function(k){return '<option>'+esc(k)+'</option>';}).join('');
 if(kprev)$('kname').value=kprev;
 var saved=Object.keys(d.keys).filter(function(k){return d.keys[k];});
 $('kstate').innerHTML=saved.length?saved.map(function(k){return esc(k)+': <span class="pill ok">'+esc(d.keys[k])+'</span>';}).join('<br>'):'<span class="pill">no keys saved</span>';
 $('aprov').onchange();
 $('gws').innerHTML=d.gateways.length?d.gateways.map(function(g){return '<div class="gw"><div><b>'+esc(g.backend)+'</b> on port '+g.port+' · model '+esc(g.model||'default')+
  ' · '+(g.requests||0)+' requests'+(g.paused?' · <span class="pill no">paused until '+esc(g.paused_until)+'</span>':'')+'</div><button class="ghost" data-stop="'+g.port+'">Stop</button></div>';}).join(''):'<p class="small">None running.</p>';
}
function load(){return api('/api/setup/state').then(function(d){$('locked').hidden=true;$('app').hidden=false;render(d);}).catch(function(){$('locked').hidden=false;$('app').hidden=true;});}
document.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
 if(b.dataset.use||b.dataset.start){var id=b.dataset.use||b.dataset.start,label=b.textContent;busy(b,true,'Starting…');
  var body={backend:id,model:$('m_'+id).value,port:+$('p_'+id).value};
  (b.dataset.use?api('/api/setup/provider',Object.assign({kind:'login'},body)):api('/api/setup/gateway',Object.assign({action:'start'},body)))
   .then(function(){msg(b.dataset.use?'Now answering with this login.':'Gateway started.');return load();}).catch(function(err){msg(err.message);}).then(function(){busy(b,false,label);});}
 if(b.dataset.stop){api('/api/setup/gateway',{action:'stop',port:+b.dataset.stop}).then(function(){msg('Gateway stopped.');load();}).catch(function(err){msg(err.message);});}
});
$('ksave').onclick=function(){var v=$('kval').value.trim();if(!v){msg('Paste a key first.');return;}
 api('/api/setup/key',{name:$('kname').value,value:v}).then(function(d){$('kval').value='';msg(d.name+' saved.');load();}).catch(function(err){msg(err.message);});};
$('ause').onclick=function(){api('/api/setup/provider',{kind:'api',provider:$('aprov').value,model:$('amodel').value.trim(),base_url:$('aurl').value.trim()})
 .then(function(){msg('Now answering with this API.');load();}).catch(function(err){msg(err.message);});};
$('test').onclick=function(){var b=this;busy(b,true,'Testing…');api('/api/setup/test',{}).then(function(d){$('tres').innerHTML=d.ok?'<span class="pill ok">working</span> replied “'+esc(d.reply)+'” in '+d.seconds+' s with '+esc(d.model):'<span class="pill no">failed</span> '+esc(d.error);})
 .catch(function(err){msg(err.message);}).then(function(){busy(b,false,'Test the connection');});};
if(T){load();}else{$('locked').hidden=false;}
</script></body></html>"""

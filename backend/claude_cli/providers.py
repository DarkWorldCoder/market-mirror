"""Private, provider-neutral setup for local MarketMirror installations (stdlib only)."""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

CATALOG = {
    "ollama": {"label": "Ollama on this computer", "base_url": "http://127.0.0.1:11434/v1", "key_required": False,
               "guide": "https://docs.ollama.com/openai", "key_env": ""},
    "lmstudio": {"label": "LM Studio on this computer", "base_url": "http://127.0.0.1:1234/v1", "key_required": False,
                 "guide": "https://lmstudio.ai/docs/developer/openai-compat", "key_env": ""},
    "anthropic": {"label": "Claude API", "base_url": "https://api.anthropic.com/v1", "key_required": True,
                  "guide": "https://platform.claude.com/docs/en/get-api-key", "key_url": "https://platform.claude.com/settings/keys", "key_env": "ANTHROPIC_API_KEY"},
    "openai": {"label": "OpenAI / ChatGPT API", "base_url": "https://api.openai.com/v1", "key_required": True,
               "guide": "https://developers.openai.com/api/docs/quickstart", "key_url": "https://platform.openai.com/api-keys", "key_env": "OPENAI_API_KEY"},
    "gemini": {"label": "Google Gemini API", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_required": True,
               "guide": "https://ai.google.dev/gemini-api/docs/openai", "key_url": "https://aistudio.google.com/apikey", "key_env": "GEMINI_API_KEY"},
    "compatible": {"label": "Another OpenAI-compatible server", "base_url": "", "key_required": True,
                   "guide": "Use your provider's API console and model identifier.", "key_env": "LLM_API_KEY"},
    "chatgpt": {"label": "ChatGPT (Sign in with ChatGPT or Codex CLI login)", "gateway": True, "gateway_name": "chatgpt",
                "guide": "codex login"},
    "siwc": {"label": "Sign in with ChatGPT (eligibility checked at login)", "gateway": True,
             "guide": "https://developers.openai.com/siwc/quickstart"},
    "codex": {"label": "Existing local Codex CLI login", "gateway": True, "guide": "codex login"},
    "claude": {"label": "Existing local Claude Code login", "gateway": True, "guide": "claude auth login"},
    "gemini_cli": {"label": "Existing local Gemini CLI login", "gateway": True, "gateway_name": "gemini", "guide": "gemini"},
    "antigravity": {"label": "Existing local Antigravity CLI login (agy; Gemini models by default)", "gateway": True,
                    "gateway_name": "antigravity", "guide": "agy"},
    "multi": {"label": "Multi-Provider Agent Pool (Claude + ChatGPT/Codex + Gemini together)", "gateway": True, "gateway_name": "multi", "guide": "mm.sh gateway start multi"},
}
KEYS = {"LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_API_KEY", "LLM_GATEWAY", "LLM_POOL", "MARKET_MIRROR_PROVIDER"}


def read_env(root: Path) -> dict:
    values = {}
    try:
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() in KEYS:
                raw = value.strip()
                try:
                    values[name.strip()] = json.loads(raw) if raw.startswith('"') else raw.strip("'")
                except ValueError:
                    values[name.strip()] = raw
    except FileNotFoundError:
        pass
    return values


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError("base URL must not include credentials, query parameters, or a fragment")
    local = parsed.hostname.lower() == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("use HTTPS for hosted providers or HTTP on loopback for a local model")
    return url.rstrip("/")


# LLM_POOL entry -> (LLM_PROVIDER, default base URL, default model) of the single provider written next to the pool
POOL_PRIMARY = {
    "claude": ("claude", "https://api.anthropic.com/v1/", "claude-haiku-4-5"),
    "anthropic": ("claude", "https://api.anthropic.com/v1/", "claude-haiku-4-5"),
    "openai": ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    "chatgpt": ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    "gpt": ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    "gemini": ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "google": ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "ollama": ("openai", "http://127.0.0.1:11434/v1", "llama3.2"),
}
GATEWAY_POOL_ENTRIES = ("codex", "antigravity", "claude_code", "gemini_cli")


def _pool_entries(pool: str) -> list:
    if pool.startswith("["):
        try:
            rows = json.loads(pool)
        except ValueError:
            raise ValueError("LLM_POOL JSON must be a list of {provider, model?, base_url?}")
        return [(str(r.get("provider") or "").lower(), str(r.get("model") or ""), str(r.get("base_url") or ""))
                for r in rows if isinstance(r, dict)]
    out = []
    for part in pool.split(","):
        prov, _, mod = part.strip().partition(":")
        if prov:
            out.append((prov.strip().lower(), mod.strip(), ""))
    return out


def primary_from_pool(pool: str, base_url: str = "", key: str = "") -> dict:
    """The single LLM_* provider that single-provider stages use when LLM_POOL is set: the first hosted entry
    (its key comes from ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY, or --key-env), else the first gateway
    entry, which needs its gateway URL (base_url or <NAME>_GATEWAY_URL) and token (key or <NAME>_GATEWAY_KEY)."""
    entries = _pool_entries(pool)
    if not entries:
        raise ValueError("LLM_POOL is empty")
    for prov, mod, url in entries:
        if prov in POOL_PRIMARY:
            llm_prov, default_url, default_model = POOL_PRIMARY[prov]
            values = {"LLM_PROVIDER": llm_prov, "LLM_BASE_URL": validate_url(url or base_url or default_url),
                      "LLM_MODEL_NAME": mod or default_model}
            if key.strip():
                values["LLM_API_KEY"] = key.strip()
            elif prov == "ollama":
                values["LLM_API_KEY"] = "local"
            return values
    for prov, mod, url in entries:
        if prov in GATEWAY_POOL_ENTRIES:
            gw_url = url or base_url or os.environ.get(f"{prov.upper()}_GATEWAY_URL", "")
            gw_key = key.strip() or os.environ.get(f"{prov.upper()}_GATEWAY_KEY", "")
            if not (gw_url and gw_key):
                raise ValueError(f"the pool's first entry {prov!r} is a login gateway: start it (mm.sh gateway start "
                                 f"{prov} --port N) and set {prov.upper()}_GATEWAY_URL / {prov.upper()}_GATEWAY_KEY")
            gateway = {"claude_code": "claude", "gemini_cli": "gemini"}.get(prov, prov)
            return {"LLM_PROVIDER": "openai", "LLM_BASE_URL": validate_url(gw_url), "LLM_API_KEY": gw_key,
                    "LLM_GATEWAY": gateway, "LLM_MODEL_NAME": mod or gateway}
    raise ValueError("LLM_POOL has no provider this setup knows (claude, openai, gemini, ollama, codex, antigravity)")


def write_config(root: Path, provider: str, model: str, base_url: str = "", key: str = "", pool: str = "") -> dict:
    spec = CATALOG[provider]
    if spec.get("gateway") and not (provider == "multi" and pool.strip()):
        raise ValueError("gateway providers use the gateway login/start commands")
    if not model.strip():
        raise ValueError("choose a model identifier installed locally or available in your provider account")
    if any(c in value for value in (model, base_url, key, pool) for c in ("\r", "\n", "\x00", "${")):
        raise ValueError("configuration values must be single-line strings")
    if provider == "multi" and pool.strip():
        # Pool-aware stages spread calls over LLM_POOL; every other stage (graph build, ontology, OASIS rounds,
        # reports) still uses the single LLM_* provider, so keep a valid one: the pool's first entry.
        values = {**primary_from_pool(pool.strip(), base_url, key),
                  "LLM_POOL": pool.strip(), "MARKET_MIRROR_PROVIDER": "multi"}
    else:
        endpoint = validate_url(base_url or spec["base_url"])
        if spec["key_required"] and not key.strip():
            raise ValueError("API key required; use a named environment variable or hidden interactive input")
        llm_prov = "claude" if provider == "anthropic" else ("gemini" if provider == "gemini" else "openai")
        values = {"LLM_PROVIDER": llm_prov,
                  "LLM_BASE_URL": endpoint, "LLM_MODEL_NAME": model.strip(),
                  "LLM_API_KEY": key.strip() if spec["key_required"] else (key.strip() or "local"),
                  "MARKET_MIRROR_PROVIDER": provider}
        if pool.strip():
            values["LLM_POOL"] = pool.strip()
    root.mkdir(parents=True, exist_ok=True)
    env = root / ".env"
    template = env if env.exists() else root / ".env.example"
    lines = template.read_text(encoding="utf-8").splitlines() if template.exists() else []
    lines = [line for line in lines if line.partition("=")[0].strip() not in KEYS]
    # JSON quoted values are understood by python-dotenv and avoid interpolation
    # or comments accidentally changing a pasted key/model identifier.
    lines += [f"{name}={json.dumps(value)}" for name, value in values.items()]
    fd, temp = tempfile.mkstemp(prefix=".env.", dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(temp, env)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return status(root)


def status(root: Path) -> dict:
    env = read_env(root)
    key = (
        env.get("LLM_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    url = urlparse(env.get("LLM_BASE_URL") or "")
    safe_url = f"{url.scheme}://{url.hostname or ''}{':' + str(url.port) if url.port else ''}{url.path}" if url.scheme else None
    return {"provider": env.get("MARKET_MIRROR_PROVIDER") or env.get("LLM_GATEWAY") or env.get("LLM_PROVIDER"),
            "model": env.get("LLM_MODEL_NAME"), "base_url": safe_url,
            "pool": env.get("LLM_POOL") or os.environ.get("LLM_POOL") or None,
            "credential_configured": bool(key and key != "your_api_key_here"), "env_file": str(root / ".env"),
            "restart_required_after_changes": True}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check(root: Path, opener=None, settings=None) -> dict:
    env = settings if settings is not None else read_env(root)
    endpoint = validate_url(env.get("LLM_BASE_URL") or "")
    key = (
        env.get("LLM_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") if env.get("LLM_PROVIDER") == "gemini" else "")
        or ""
    )
    headers = {"Authorization": "Bearer " + key}
    if env.get("LLM_PROVIDER") == "claude":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    request = urllib.request.Request(endpoint + "/models", headers=headers)
    opener = opener or urllib.request.build_opener(_NoRedirect).open
    try:
        with opener(request, timeout=15) as response:
            data = json.loads(response.read(2_000_000))
        raw_models = [str(row["id"]) for row in data.get("data", []) if isinstance(row, dict) and row.get("id")]
        models = [m.split("/", 1)[1] if m.startswith("models/") else m for m in raw_models]
        selected = env.get("LLM_MODEL_NAME")
        norm_selected = selected.split("/", 1)[1] if isinstance(selected, str) and selected.startswith("models/") else selected
        return {"status": "reachable", "models": models, "selected_model": selected,
                "model_listed": bool(norm_selected and (norm_selected in models or selected in raw_models)), "inference_tested": False,
                "note": "Model discovery does not prove tool-calling support; run a small fixture before a large simulation."}
    except urllib.error.HTTPError as error:
        reason = {401: "authentication_failed", 403: "access_denied", 429: "rate_limited"}.get(error.code, "provider_error")
        return {"status": reason, "http_status": error.code, "inference_tested": False}
    except (OSError, ValueError):
        return {"status": "unreachable_or_invalid_response", "inference_tested": False}


def configure(root: Path, args) -> dict:
    provider = args.provider
    if not provider:
        if not sys.stdin.isatty():
            raise ValueError("noninteractive setup needs --provider and --model; secrets belong in --key-env")
        print("Choose a model provider (local models need no hosted API key):", file=sys.stderr)
        for name, spec in CATALOG.items():
            print(f"  {name}: {spec['label']}", file=sys.stderr)
        provider = input("Provider [ollama]: ").strip() or "ollama"
    if provider not in CATALOG:
        raise ValueError("unknown provider; use provider list")
    spec = CATALOG[provider]
    if spec.get("gateway"):
        helper = root / "plugin/skills/market-mirror/scripts/mm.sh"
        gw_target = spec.get("gateway_name", provider)
        action = "login" if gw_target == "siwc" else "start"
        return {"provider": provider, "status": "login_required", "guide": spec["guide"],
                "command": ["bash", str(helper), "gateway", action, gw_target],
                "next": "After login, run gateway start siwc." if gw_target == "siwc" else "Start the gateway using the command above."}
    model, endpoint = args.model or "", args.base_url or spec["base_url"]
    if not endpoint and sys.stdin.isatty():
        endpoint = input("OpenAI-compatible base URL (HTTPS or local loopback): ").strip()
    key = ""
    if spec["key_required"]:
        variable = args.key_env or spec["key_env"]
        key = os.environ.get(variable, "")
        if not key and provider == "gemini" and not args.key_env:
            key = os.environ.get("GOOGLE_API_KEY", "")
        if not key and sys.stdin.isatty():
            print("Create a key in your provider's account: " + spec.get("key_url", spec["guide"]), file=sys.stderr)
            if getattr(args, "open_guide", False) and spec.get("key_url"):
                webbrowser.open(spec["key_url"])
            key = getpass.getpass("API key (hidden, saved privately on this computer): ")
    if not model and sys.stdin.isatty():
        discovery = check(root, settings={"LLM_BASE_URL": endpoint, "LLM_API_KEY": key or "local",
                                         "LLM_PROVIDER": "claude" if provider == "anthropic" else "openai"})
        models = discovery.get("models") or []
        if models:
            print("Available models: " + ", ".join(models[:20]), file=sys.stderr)
        else:
            print("Model discovery: " + discovery["status"] + ". Enter a model identifier from your provider.", file=sys.stderr)
        model = input("Model identifier: ").strip()
    return write_config(root, provider, model, endpoint, key)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "status", "configure", "check"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--provider", choices=tuple(CATALOG))
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--key-env", help="name of an environment variable containing the key; never pass the key as an argument")
    parser.add_argument("--open-guide", action="store_true", help="open the official key console while configuring interactively")
    args = parser.parse_args(argv)
    try:
        result = CATALOG if args.action == "list" else status(args.root) if args.action == "status" else \
                 check(args.root) if args.action == "check" else configure(args.root, args)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") not in ("authentication_failed", "access_denied", "rate_limited", "provider_error", "unreachable_or_invalid_response") else 1
    except (ValueError, OSError) as error:
        # Only our validation errors are printed; upstream exception bodies may contain credentials.
        print(json.dumps({"success": False, "error": str(error) if isinstance(error, ValueError) else "Could not read or save provider configuration"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

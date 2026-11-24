"""Safe workspace configuration for the engine's existing memory and decision adapters."""
import os
import json
import math
import threading
from urllib.parse import urlsplit

from ..config import Config
from . import jev
from ..utils.model_pool import PROVIDER_DEFAULTS, provider_api_key
from ..utils import spend_cap

_LOCK = threading.RLock()
_RESTART_REQUIRED = False
_MEMORY_FIELDS = {"backend", "embeddings", "extract_activity", "cognee_url", "zep_api_key"}
_LLM_FIELDS = {"provider", "model", "base_url", "api_key", "pool"}
_SPENDING_FIELDS = {"process_limit_usd", "input_price_usd_per_mtok", "output_price_usd_per_mtok"}
_JEV_FIELDS = {"route", "model", "parallel", "timeout", "retries", "labels", "ssr_engine", "api_key"}


def _public_url(value):
    """Avoid disclosing credentials from an older manually configured sidecar URL."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = host + (f":{parsed.port}" if parsed.port else "")
        return parsed._replace(netloc=netloc, query="", fragment="").geturl()
    except ValueError:
        return ""


def state():
    decision = jev.settings()
    return {
        "memory": {
            "backend": Config.MEMORY_BACKEND, "embeddings": Config.MEMORY_EMBEDDINGS,
            "extract_activity": Config.MEMORY_EXTRACT_ACTIVITY, "embed_model": Config.MEMORY_EMBED_MODEL,
            "cognee_url": _public_url(Config.COGNEE_SIDECAR_URL), "zep_key_configured": bool(Config.ZEP_API_KEY),
            "providers": [
                {"id": "local", "label": "Local memory", "supported": True, "configured": True,
                 "description": "SQLite graph memory on this computer. No API key required."},
                {"id": "cognee", "label": "Cognee", "supported": True, "configured": bool(Config.COGNEE_SIDECAR_URL),
                 "description": "Graph extraction and search through your Cognee sidecar. Connection has not been tested."},
                {"id": "zep", "label": "Zep Cloud", "supported": True, "configured": bool(Config.ZEP_API_KEY),
                 "description": "Cloud graph memory using your Zep API key. Connection has not been tested."},
                {"id": "supermemory", "label": "Supermemory", "supported": False, "configured": False,
                 "description": "This engine does not include a Supermemory adapter. Choose Local, Cognee or Zep."},
            ],
        },
        "jev": {key: decision.get(key) for key in ("configured", "route", "model", "parallel", "timeout", "retries", "reason", "ssr_engine")}
               | {"key_configured": bool(decision.get("configured")),
                  "labels": os.environ.get("MM_JEV_LABELS", "auto"),
                  "custom_endpoint": bool(os.environ.get("JEV_BASE_URL"))},
        "llm": _llm_state(),
        "spending": _spending_state(),
        "restart_required": _RESTART_REQUIRED,
        "connection_tested": False,
    }


def _text(value, field, maximum=4096):
    if not isinstance(value, str) or len(value) > maximum or any(c in value for c in ("\r", "\n", "\x00", "${")):
        raise ValueError(f"{field} must be a single line of at most {maximum} characters")
    return value.strip()


def _choice(value, choices, field):
    if value not in choices:
        raise ValueError(f"{field} must be one of {', '.join(choices)}")
    return value


def update(data):
    global _RESTART_REQUIRED
    from ..api.setup import _write_env

    if not isinstance(data, dict) or not data or set(data) - {"memory", "jev", "llm", "spending"}:
        raise ValueError("Provide memory, jev, llm or spending settings")
    values = {}
    memory = data.get("memory", {})
    decision = data.get("jev", {})
    if not isinstance(memory, dict) or set(memory) - _MEMORY_FIELDS:
        raise ValueError("Unsupported memory setting")
    if not isinstance(decision, dict) or set(decision) - _JEV_FIELDS:
        raise ValueError("Unsupported Jev setting")
    for field, value in memory.items():
        if field == "backend":
            values["MEMORY_BACKEND"] = _choice(value, ("local", "cognee", "zep"), field)
        elif field in {"embeddings", "extract_activity"}:
            if type(value) is not bool:
                raise ValueError(f"{field} must be true or false")
            values[{"embeddings": "MEMORY_EMBEDDINGS", "extract_activity": "MEMORY_EXTRACT_ACTIVITY"}[field]] = str(value).lower()
        elif field == "cognee_url":
            value = _text(value, field, 2048).rstrip("/")
            parsed = urlsplit(value)
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("Cognee URL has an invalid port") from exc
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
                raise ValueError("Use a Cognee HTTP or HTTPS URL without credentials, query or fragment")
            values["COGNEE_SIDECAR_URL"] = value
        elif field == "zep_api_key":
            value = _text(value, field)
            if value:
                values["ZEP_API_KEY"] = value
    for field, value in decision.items():
        if field == "route":
            values["JEV_VIA"] = _choice(value, ("typesafe", "openrouter"), field)
        elif field == "model":
            values["JEV_MODEL"] = _text(value, field, 200) or None
        elif field in {"parallel", "timeout", "retries"}:
            low, high = {"parallel": (1, 32), "timeout": (5, 600), "retries": (0, 8)}[field]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{field} must be an integer from {low} to {high}")
            values[f"JEV_{field.upper()}"] = str(value)
        elif field == "labels":
            values["MM_JEV_LABELS"] = _choice(value, ("auto", "on", "off"), field)
        elif field == "ssr_engine":
            values["SSR_ENGINE"] = _choice(value, ("embeddings", "jev"), field)
        elif field == "api_key":
            value = _text(value, field)
            if value:
                route = decision.get("route", jev.settings()["route"])
                values["OPENROUTER_API_KEY" if route == "openrouter" else "TYPESAFE_API_KEY"] = value
    values.update(_llm_values(data.get("llm", {})))
    values.update(_spending_values(data.get("spending", {})))
    with _LOCK:
        if values.get("MEMORY_BACKEND", Config.MEMORY_BACKEND) == "zep" and not (values.get("ZEP_API_KEY") or Config.ZEP_API_KEY):
            raise ValueError("Add a Zep API key before selecting Zep Cloud")
        # Reuse the setup wizard's atomic 0600 .env writer. Never return these values.
        _write_env(values)
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key in ("MEMORY_BACKEND", "COGNEE_SIDECAR_URL", "ZEP_API_KEY"):
            if key in values:
                setattr(Config, key, values[key])
        for key in ("MEMORY_EMBEDDINGS", "MEMORY_EXTRACT_ACTIVITY"):
            if key in values:
                setattr(Config, key, values[key] == "true")
        for field, key in (("LLM_PROVIDER", "LLM_PROVIDER"), ("LLM_MODEL_NAME", "LLM_MODEL_NAME"),
                           ("LLM_BASE_URL", "LLM_BASE_URL"), ("LLM_API_KEY", "LLM_API_KEY"), ("LLM_POOL", "LLM_POOL")):
            if key in values:
                setattr(Config, field, values[key] or "")
        # Existing graph clients can be in use by a running task. Restart instead of closing them.
        _RESTART_REQUIRED = _RESTART_REQUIRED or bool(memory)
        return state()



def _cloud_providers():
    return {key: value for key, value in PROVIDER_DEFAULTS.items() if not value.get("gateway") and key != "chatgpt"}


def _pool_safe(value):
    # Legacy JSON pools may contain inline API keys. Never serialize those keys.
    if value.lstrip().startswith("["):
        try:
            rows = json.loads(value)
            return json.dumps([{key: (_public_url(row[key]) if key == "base_url" else row[key])
                                for key in ("provider", "model", "base_url") if key in row}
                               for row in rows if isinstance(row, dict)])
        except (ValueError, TypeError):
            return ""
    return value


def _credential_set(value):
    return bool(value and value != "local" and value != os.environ.get("MM_WORKER_SECRET"))


def _provider_override(name, field, fallback):
    endpoint = os.environ.get(f"{name.upper()}_BASE_URL", "")
    if "/hosted/v1" in endpoint:
        return fallback
    return os.environ.get(f"{name.upper()}_{field}") or fallback


def _llm_state():
    return {"provider": Config.LLM_PROVIDER, "model": Config.LLM_MODEL_NAME,
            "base_url": _public_url(Config.LLM_BASE_URL), "api_key_configured": _credential_set(Config.LLM_API_KEY),
            "gateway": os.environ.get("LLM_GATEWAY") or None,
            "pool": _pool_safe(Config.LLM_POOL),
            "providers": [{"id": name, "label": spec.get("label") or {"claude": "Anthropic", "openai": "OpenAI", "gemini": "Google Gemini", "ollama": "Ollama"}.get(name, name),
                           "model": _provider_override(name, "MODEL_NAME", spec["model"]),
                           "base_url": _public_url(_provider_override(name, "BASE_URL", spec["base_url"])),
                           "key_configured": _credential_set(provider_api_key(name)) or (name == Config.LLM_PROVIDER and _credential_set(Config.LLM_API_KEY) and not os.environ.get("LLM_GATEWAY"))}
                          for name, spec in _cloud_providers().items()]}


def _spending_state():
    process = spend_cap.process_spent()
    override = os.environ.get("MM_USD_PER_MTOK", "")
    try:
        prices = [float(v) for v in override.split(",")]
        if len(prices) != 2 or not all(math.isfinite(v) and v >= 0 for v in prices):
            prices = [None, None]
    except ValueError:
        prices = [None, None]
    return {"process_limit_usd": spend_cap._process_limit() or 0,
            "process_spent_usd": process["spent_usd"], "process_calls": process["calls"],
            "run_cap": spend_cap.status(), "input_price_usd_per_mtok": prices[0], "output_price_usd_per_mtok": prices[1],
            "enforcement": "Stops new instrumented model calls after estimated spend reaches the limit. In-flight calls may exceed it. Each process has its own counter, reset on restart. Jev and external provider charges are not covered."}


def _url(value, field):
    value = _text(value, field, 2048).rstrip("/")
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} has an invalid port") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError(f"{field} must be an HTTP or HTTPS URL without credentials, query or fragment")
    return value


def _pool_value(value):
    value = _text(value, "pool", 10000)
    if not value or value.lower() == "auto":
        return value.lower()
    if value.startswith("["):
        try:
            rows = json.loads(value)
        except ValueError as exc:
            raise ValueError("Pool must be provider names or a JSON list") from exc
        if not isinstance(rows, list) or len(rows) > 30:
            raise ValueError("Use at most 30 pool entries")
        normalized = []
        for row in rows:
            if not isinstance(row, dict) or set(row) - {"provider", "model", "base_url"}:
                raise ValueError("Pool entries accept provider, model and base_url. Save keys separately.")
            name = row.get("provider")
            if name not in PROVIDER_DEFAULTS:
                raise ValueError("Unknown pool provider")
            normalized.append({"provider": name, **({"model": _text(row["model"], "model", 200)} if "model" in row else {}),
                               **({"base_url": _url(row["base_url"], "base_url")} if "base_url" in row else {})})
        return json.dumps(normalized)
    parts = value.split(",")
    if len(parts) > 30:
        raise ValueError("Use at most 30 pool entries")
    for part in parts:
        name, _, model = part.strip().partition(":")
        if name not in PROVIDER_DEFAULTS:
            raise ValueError(f"Unknown pool provider: {name[:100]}")
    return ",".join(part.strip() for part in parts)


def _llm_values(data):
    if not isinstance(data, dict) or set(data) - _LLM_FIELDS:
        raise ValueError("Unsupported model setting")
    if not data:
        return {}
    values = {}
    if "pool" in data:
        values["LLM_POOL"] = _pool_value(data["pool"])
    if set(data) == {"pool"}:
        return values
    name = data.get("provider", Config.LLM_PROVIDER)
    spec = _cloud_providers().get(name)
    if not spec:
        raise ValueError("Choose a supported API provider")
    same = name == Config.LLM_PROVIDER and not os.environ.get("LLM_GATEWAY")
    model = _text(data.get("model", Config.LLM_MODEL_NAME if same else spec["model"]), "model", 200)
    base_url = _url(data.get("base_url", Config.LLM_BASE_URL if same else spec["base_url"]), "base_url")
    if not model:
        raise ValueError("Enter a model identifier available in your provider account")
    key = _text(data.get("api_key", ""), "api_key")
    provided_key = key
    # A blank field retains only a key belonging to this provider, never an unrelated gateway token.
    if not key:
        key = provider_api_key(name) or (Config.LLM_API_KEY if same or (name == "custom" and base_url == Config.LLM_BASE_URL.rstrip("/")) else "") or ""
    if not provided_key and key == os.environ.get("MM_WORKER_SECRET") and base_url != Config.LLM_BASE_URL.rstrip("/"):
        key = ""
    if name in {"ollama", "custom"}:
        key = key or "local"
    if not key:
        raise ValueError("Enter an API key for the selected provider")
    values.update({"LLM_PROVIDER": name, "LLM_MODEL_NAME": model, "LLM_BASE_URL": base_url,
                   "LLM_API_KEY": key, "LLM_GATEWAY": None,
                   f"{name.upper()}_MODEL_NAME": model, f"{name.upper()}_BASE_URL": base_url})
    if spec.get("key_env"):
        values[spec["key_env"]] = key
    return values


def _nonnegative(value, field):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1000000:
        raise ValueError(f"{field} must be a finite number from 0 to 1000000")
    return float(value)


def _spending_values(data):
    if not isinstance(data, dict) or set(data) - _SPENDING_FIELDS:
        raise ValueError("Unsupported spending setting")
    values = {}
    if "process_limit_usd" in data:
        values["MM_MAX_SPEND_USD"] = str(_nonnegative(data["process_limit_usd"], "process_limit_usd"))
    prices = {"input_price_usd_per_mtok", "output_price_usd_per_mtok"}
    if prices & set(data):
        if not prices <= set(data):
            raise ValueError("Provide both input and output price overrides")
        if all(data[field] is None for field in prices):
            values["MM_USD_PER_MTOK"] = None
        else:
            values["MM_USD_PER_MTOK"] = ",".join(str(_nonnegative(data[field], field)) for field in ("input_price_usd_per_mtok", "output_price_usd_per_mtok"))
    return values

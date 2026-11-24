"""Bounded discovery of installed models on local model servers only."""
import ipaddress
import json
import os
import threading
import time
from urllib.parse import urlsplit

import urllib3

from ..config import Config

_CACHE = None
_LOCK = threading.Lock()


def _target(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
        address = "127.0.0.1" if host == "localhost" else host
        if parsed.scheme != "http" or not address or not ipaddress.ip_address(address).is_loopback or not port or not 1024 <= port <= 65535:
            return None
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            return None
        if parsed.path.rstrip("/") not in ("", "/v1"):
            return None
        return address, port
    except ValueError:
        return None


def _get(base_url, path, key=None):
    target = _target(base_url)
    if not target:
        raise ValueError("Only configured loopback HTTP model endpoints are supported")
    pool = urllib3.HTTPConnectionPool(*target, timeout=urllib3.Timeout(connect=0.5, read=1.5), retries=False)
    response = None
    try:
        headers = {"Accept": "application/json"}
        if key and key != "local":
            headers["Authorization"] = "Bearer " + key
        response = pool.urlopen("GET", path, headers=headers, redirect=False, preload_content=False)
        if response.status != 200:
            raise ValueError("Model server is unavailable or requires authentication")
        raw = bytearray()
        deadline = time.monotonic() + 2.5
        while len(raw) <= 512000:
            if time.monotonic() >= deadline:
                raise ValueError("Local model catalog exceeded its time limit")
            chunk = response.read1(8192, decode_content=True)
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > 512000:
            raise ValueError("Local model catalog exceeds its size limit")
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("Local model catalog is unavailable or invalid") from None
    except Exception:
        raise ValueError("Local model server is not reachable") from None
    finally:
        if response is not None:
            response.close()
        pool.close()


def discover(refresh=False):
    global _CACHE
    signature = (Config.LLM_BASE_URL, Config.LLM_API_KEY, os.environ.get("OLLAMA_BASE_URL"),
                 os.environ.get("LMSTUDIO_BASE_URL"), bool(os.environ.get("MM_WORKER_SECRET")), os.environ.get("MM_HOSTED_WORKER"))
    with _LOCK:
        if not refresh and _CACHE and _CACHE[0] == signature and time.time() - _CACHE[1]["checked_at"] < 60:
            return _CACHE[1]
    targets = []
    if _target(Config.LLM_BASE_URL):
        provider = "ollama" if _target(Config.LLM_BASE_URL)[1] == 11434 else "lmstudio" if _target(Config.LLM_BASE_URL)[1] == 1234 else "configured"
        targets.append((provider, Config.LLM_BASE_URL, Config.LLM_API_KEY))
    hosted = bool(os.environ.get("MM_WORKER_SECRET")) or os.environ.get("MM_HOSTED_WORKER", "").lower() in {"1", "true", "yes"}
    for provider, key, fallback in (("ollama", "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"), ("lmstudio", "LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")):
        value = os.environ.get(key) or ("" if hosted else fallback)
        if _target(value) and all(_target(value) != _target(row[1]) for row in targets):
            targets.append((provider, value, None))
    models, sources = [], []
    truncated = False
    for provider, base_url, key in targets:
        try:
            if provider == "ollama":
                data = _get(base_url, "/api/tags", key)
                entries = data.get("models", []) if isinstance(data, dict) else []
                identifiers = [row.get("name") or row.get("model") for row in entries if isinstance(row, dict)]
            else:
                data = _get(base_url, "/v1/models", key)
                entries = data.get("data", []) if isinstance(data, dict) else []
                identifiers = [row.get("id") for row in entries if isinstance(row, dict)]
            if not isinstance(entries, list):
                raise ValueError("Local model server returned an invalid catalog")
            identifiers = list(dict.fromkeys(value for value in identifiers if isinstance(value, str) and 0 < len(value) <= 200 and not any(ord(c) < 32 for c in value)))
            truncated = truncated or len(models) + len(identifiers) > 300
            for identifier in identifiers:
                if len(models) >= 300:
                    break
                models.append({"id": identifier, "provider": provider, "base_url": base_url.rstrip("/").removesuffix("/v1") + "/v1", "source": "/api/tags" if provider == "ollama" else "/v1/models"})
                if len(models) >= 300:
                    break
            sources.append({"provider": provider, "base_url": base_url, "available": True, "error": None})
        except ValueError as exc:
            sources.append({"provider": provider, "base_url": base_url, "available": False, "error": str(exc)})
    value = {"models": models, "sources": sources, "checked_at": time.time(), "truncated": truncated}
    with _LOCK:
        _CACHE = signature, value
    return value



def cached_local_models():
    """Previously discovered model IDs only; never scan as a side effect of a chat request."""
    with _LOCK:
        if not _CACHE:
            return []
        return [dict(row) for row in _CACHE[1]["models"]]


def key_for_local_model(base_url):
    """Server-only credential resolution for an already discovered loopback endpoint."""
    if not _target(base_url) or not any(row["base_url"] == base_url for row in cached_local_models()):
        raise ValueError("Discover this local endpoint before selecting its models")
    if _target(base_url) == _target(Config.LLM_BASE_URL):
        return Config.LLM_API_KEY or "local"
    return "local"

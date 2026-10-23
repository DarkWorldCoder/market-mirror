"""
Multi-Provider Agent Pool (`MultiProviderPool`).

Allows MarketMirror to run Claude, OpenAI/ChatGPT, Google Gemini, hosted OpenAI-compatible APIs (DeepSeek, Kimi,
Mistral, xAI, Groq, Together, Fireworks, OpenRouter, Qwen, Z.ai, Cerebras, MiniMax) and local models
concurrently in a single simulation or research run:
- Deterministic agent-to-provider assignment (`for_agent(agent_id)`) so a simulated
  person stays on a consistent model family across steps unless that provider hits a 429.
- Round-robin batch balancing (`for_slot(i)` or direct `.chat.completions.create(...)`).
- Automatic failover across healthy providers when one provider hits a 429 rate limit
  or transient 5xx upstream failure, rewriting the target model and request parameters
  for the backup provider automatically.
- Per-provider telemetry (`calls`, `input_tokens`, `output_tokens`, `failures`, `rate_limits`)
  for cross-model agreement & bias diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "claude": {
        "base_url": "https://api.anthropic.com/v1/",
        "model": "claude-haiku-4-5",
        "key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "chatgpt": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    # Login-based CLIs are reached only through a local MarketMirror gateway (backend/gateway/local_gateway.py):
    # base URL and bearer token come from <NAME>_GATEWAY_URL / <NAME>_GATEWAY_KEY, never from an API key.
    "codex": {
        "base_url": "",
        "model": "codex",
        "key_env": "CODEX_GATEWAY_KEY",
        "gateway": "codex",
    },
    "antigravity": {
        "base_url": "",
        "model": "gemini-4-argon-medium",
        "key_env": "ANTIGRAVITY_GATEWAY_KEY",
        "gateway": "antigravity",
    },
    "claude_code": {
        "base_url": "",
        "model": "sonnet",
        "key_env": "CLAUDE_CODE_GATEWAY_KEY",
        "gateway": "claude",
    },
    "gemini_cli": {
        "base_url": "",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_CLI_GATEWAY_KEY",
        "gateway": "gemini",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
        "alt_key_envs": ("GOOGLE_API_KEY",),
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "llama3.2",
        "key_env": "",
    },
}

# Hosted OpenAI-compatible APIs reached with their own key. key_env is the provider's documented variable and
# alt_key_envs are read too; hosts name the provider of a base URL. qwen needs QWEN_BASE_URL (Model Studio URLs carry
# the workspace id) and custom needs CUSTOM_BASE_URL and CUSTOM_MODEL_NAME.
API_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
                 "key_env": "DEEPSEEK_API_KEY", "hosts": ("deepseek.com",)},
    "kimi": {"label": "Kimi (Moonshot AI)", "base_url": "https://api.moonshot.ai/v1", "model": "kimi-k2.6",
             "key_env": "MOONSHOT_API_KEY", "alt_key_envs": ("KIMI_API_KEY",), "hosts": ("moonshot.ai", "moonshot.cn", "kimi.ai")},
    "mistral": {"label": "Mistral", "base_url": "https://api.mistral.ai/v1", "model": "mistral-small-latest",
                "key_env": "MISTRAL_API_KEY", "hosts": ("mistral.ai",)},
    "xai": {"label": "xAI (Grok)", "base_url": "https://api.x.ai/v1", "model": "grok-4.3",
            "key_env": "XAI_API_KEY", "alt_key_envs": ("GROK_API_KEY",), "hosts": ("x.ai",)},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
             "key_env": "GROQ_API_KEY", "hosts": ("groq.com",)},
    "together": {"label": "Together AI", "base_url": "https://api.together.ai/v1", "model": "openai/gpt-oss-120b",
                 "key_env": "TOGETHER_API_KEY", "hosts": ("together.ai", "together.xyz")},
    "fireworks": {"label": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1",
                  "model": "accounts/fireworks/models/gpt-oss-120b", "key_env": "FIREWORKS_API_KEY", "hosts": ("fireworks.ai",)},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-oss-120b",
                   "key_env": "OPENROUTER_API_KEY", "hosts": ("openrouter.ai",)},
    "qwen": {"label": "Qwen (Alibaba Model Studio)", "base_url": "", "model": "qwen3.8-flash",
             "key_env": "DASHSCOPE_API_KEY", "alt_key_envs": ("QWEN_API_KEY",), "hosts": ("aliyuncs.com",)},
    "zhipu": {"label": "Z.ai (GLM)", "base_url": "https://api.z.ai/api/paas/v4/", "model": "glm-5.3-flash",
              "key_env": "ZAI_API_KEY", "alt_key_envs": ("ZHIPU_API_KEY",), "hosts": ("z.ai", "bigmodel.cn")},
    "cerebras": {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "model": "gpt-oss-120b",
                 "key_env": "CEREBRAS_API_KEY", "hosts": ("cerebras.ai",)},
    "minimax": {"label": "MiniMax", "base_url": "https://api.minimax.io/v1", "model": "MiniMax-M3.1-Flash",
                "key_env": "MINIMAX_API_KEY", "hosts": ("minimax.io", "minimaxi.com")},
    "custom": {"label": "Another OpenAI-compatible API", "base_url": "", "model": "", "key_env": "CUSTOM_API_KEY"},
}
PROVIDER_DEFAULTS.update(API_PROVIDERS)
# model id prefixes that name the family of a requested model (hosts such as Groq or OpenRouter serve many families)
_MODEL_PREFIXES = (("deepseek", ("deepseek-",)), ("kimi", ("kimi-", "moonshot-")),
                   ("mistral", ("mistral-", "ministral-", "magistral-", "codestral-", "devstral-", "pixtral-")),
                   ("xai", ("grok-",)), ("zhipu", ("glm-",)), ("qwen", ("qwen-", "qwen2", "qwen3")), ("minimax", ("minimax-",)))

PROVIDER_ALIASES = {
    "anthropic": "claude",
    "claude": "claude",
    "openai": "openai",
    "chatgpt": "chatgpt",
    "gpt": "openai",
    "codex": "codex",
    "gemini": "gemini",
    "google": "gemini",
    "ollama": "ollama",
    "local": "ollama",
    "antigravity": "antigravity",
    "agy": "antigravity",
    "claude_code": "claude_code",
    "gemini_cli": "gemini_cli",
    "deepseek": "deepseek",
    "kimi": "kimi",
    "moonshot": "kimi",
    "moonshotai": "kimi",
    "mistral": "mistral",
    "mistralai": "mistral",
    "xai": "xai",
    "grok": "xai",
    "groq": "groq",
    "together": "together",
    "togetherai": "together",
    "fireworks": "fireworks",
    "openrouter": "openrouter",
    "qwen": "qwen",
    "dashscope": "qwen",
    "alibaba": "qwen",
    "zhipu": "zhipu",
    "glm": "zhipu",
    "zai": "zhipu",
    "z.ai": "zhipu",
    "cerebras": "cerebras",
    "minimax": "minimax",
    "custom": "custom",
}
GATEWAY_PROVIDERS = ("codex", "antigravity", "claude_code", "gemini_cli")
# what a gateway's /health "backend" field means as a pool provider label
GATEWAY_BACKEND_LABELS = {"claude": "claude", "codex": "codex", "chatgpt": "codex", "siwc": "codex",
                          "gemini": "gemini", "antigravity": "antigravity", "multi": "multi"}
_GENERIC_NAMES = ("", "openai", "custom", "compatible", "multi", "gateway")
_LOCAL_MODEL_PORTS = {11434: "ollama", 1234: "ollama"}          # Ollama, LM Studio
_GATEWAY_LABEL_CACHE: Dict[str, Any] = {}
_GATEWAY_LABEL_LOCK = threading.Lock()


def _loopback_port(base_url: Optional[str]) -> Optional[int]:
    """The port of a loopback http(s) URL, else None."""
    from urllib.parse import urlparse
    try:
        u = urlparse((base_url or "").strip())
        host = (u.hostname or "").lower()
        if host in ("127.0.0.1", "localhost", "::1") or host.endswith(".localhost"):
            return u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        return None
    return None


def gateway_label(base_url: str, env: Optional[Dict[str, str]] = None, ttl: float = 60.0) -> Optional[str]:
    """Provider label of a local MarketMirror gateway at `base_url`: its /health "backend" (claude, codex, gemini,
    antigravity, multi), else LLM_GATEWAY when base_url is the configured LLM_BASE_URL. Cached for `ttl` seconds."""
    env_map = os.environ if env is None else env
    key = (base_url or "").rstrip("/")
    now = time.time()
    with _GATEWAY_LABEL_LOCK:
        hit = _GATEWAY_LABEL_CACHE.get(key)
        if hit and now - hit[1] < ttl:
            return hit[0]
    label = None
    try:
        import urllib.request
        root = key[:-3] if key.endswith("/v1") else key
        with urllib.request.urlopen(root + "/health", timeout=1.0) as r:
            data = json.loads(r.read(200_000) or b"{}")
        backend = str(data.get("backend") or "").lower()
        label = GATEWAY_BACKEND_LABELS.get(backend, backend or None)
    except Exception:  # noqa: BLE001 - not a gateway, or not running
        label = None
    if not label and key and key == (env_map.get("LLM_BASE_URL") or "").rstrip("/"):
        gw = (env_map.get("LLM_GATEWAY") or "").strip().lower()
        label = GATEWAY_BACKEND_LABELS.get(gw, gw or None)
    with _GATEWAY_LABEL_LOCK:
        _GATEWAY_LABEL_CACHE[key] = (label, now)
    return label


def api_provider_for_url(base_url: Optional[str]) -> Optional[str]:
    """The hosted API provider (deepseek, kimi, groq, ...) whose host serves `base_url`, else None."""
    from urllib.parse import urlparse
    try:
        host = (urlparse((base_url or "").strip()).hostname or "").lower()
    except ValueError:
        return None
    for prov, spec in API_PROVIDERS.items():
        if any(host == h or host.endswith("." + h) for h in spec.get("hosts", ())):
            return prov
    return None


def provider_api_key(provider: str, env: Optional[Dict[str, str]] = None) -> str:
    """The key of a hosted API provider from its own variables (key_env, then alt_key_envs); empty when unset."""
    env_map = os.environ if env is None else env
    spec = PROVIDER_DEFAULTS.get(provider) or {}
    for name in (spec.get("key_env"), *spec.get("alt_key_envs", ())):
        if name and env_map.get(name):
            return env_map[name]
    return ""


def canonical_provider(name: Optional[str], base_url: Optional[str] = None, model: Optional[str] = None,
                       env: Optional[Dict[str, str]] = None) -> str:
    """Resolve a canonical provider name ('claude', 'openai', 'gemini', 'ollama', 'codex', 'deepseek', ...).

    A loopback URL that is a MarketMirror gateway is labelled by what the gateway runs (its /health backend, or
    LLM_GATEWAY), never as "openai", even when LLM_PROVIDER=openai (the gateway speaks the OpenAI format)."""
    raw = (name or "").strip().lower()
    if raw not in _GENERIC_NAMES and raw in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[raw]
    url = (base_url or "").strip().lower()
    mod = (model or "").strip().lower()
    port = _loopback_port(url)
    if port is not None:
        if port in _LOCAL_MODEL_PORTS:
            return _LOCAL_MODEL_PORTS[port]
        label = gateway_label(base_url or "", env)
        if label:
            return label
    if raw in PROVIDER_ALIASES and raw != "custom":
        return PROVIDER_ALIASES[raw]
    hosted = api_provider_for_url(url)
    if hosted:
        return hosted
    if "anthropic.com" in url or mod.startswith("claude"):
        return "claude"
    if "generativelanguage.googleapis.com" in url or mod.startswith("gemini") or mod.startswith("models/gemini"):
        return "gemini"
    if "openai.com" in url or mod.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if not url:
        for prov, prefixes in _MODEL_PREFIXES:
            if mod.startswith(prefixes):
                return prov
    if port is not None:
        return "gateway"
    return raw or "openai"


_STATUS_429 = re.compile(r"(?:error code|status(?: code)?|http(?:/[\d.]+)?|code)\s*[:=]?\s*429\b")
_TIMEOUT_TYPES = {"APITimeoutError", "APIConnectionError", "Timeout", "TimeoutError", "ReadTimeout", "ConnectTimeout",
                  "ConnectError", "RemoteProtocolError"}
TRANSIENT_PAUSE_S = float(os.environ.get("LLM_POOL_TRANSIENT_PAUSE_S") or 15)
MAX_WAIT_S = float(os.environ.get("LLM_POOL_MAX_WAIT_S") or 20)


def _status_of(err: Exception) -> Optional[int]:
    status = getattr(err, "status_code", None) or getattr(err, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _is_timeout(err: Exception) -> bool:
    if isinstance(err, TimeoutError):
        return True
    names = {c.__name__ for c in type(err).__mro__}
    return bool(names & _TIMEOUT_TYPES) or _status_of(err) in (408, 504)


def _is_rate_limit(err: Exception) -> bool:
    """A provider rate limit / quota: HTTP 429, or the provider's own wording. A bare "429" inside unrelated text
    (a token count, an id, a price) does not count."""
    if _status_of(err) == 429 or type(err).__name__ == "RateLimitError":
        return True
    text = str(err).lower()
    if _STATUS_429.search(text):
        return True
    return any(token in text for token in ("rate limit", "rate_limit", "quota exceeded", "exceeded your current quota",
                                           "insufficient_quota", "too many requests", "resource_exhausted",
                                           "usage limit", "usage is limited"))


def _is_rate_limit_or_transient(err: Exception) -> bool:
    if _status_of(err) in (408, 429, 500, 502, 503, 504, 529) or _is_rate_limit(err) or _is_timeout(err):
        return True
    text = str(err).lower()
    return any(token in text for token in ("overloaded", "temporarily unavailable", "timed out", "connection error",
                                           "connection refused", "bad gateway", "service unavailable"))


def _retry_after(err: Exception) -> Optional[float]:
    """Seconds from a Retry-After header on an SDK error, if any."""
    resp = getattr(err, "response", None)
    try:
        value = resp.headers.get("retry-after") if resp is not None else None
        return float(value) if value else None
    except (AttributeError, TypeError, ValueError):
        return None


def answered_provider(resp: Any) -> Optional[str]:
    """The backend a MarketMirror gateway reports as having produced `resp` (its "provider" field), if any."""
    value = getattr(resp, "provider", None)
    if not isinstance(value, str):
        extra = getattr(resp, "model_extra", None)
        value = extra.get("provider") if isinstance(extra, dict) else None
    if isinstance(value, str) and value.strip():
        return GATEWAY_BACKEND_LABELS.get(value.strip().lower(), value.strip().lower())
    return None


# a gateway slot and the backend it reports answer for the same model family
_FAMILY = {"claude_code": "claude", "anthropic": "claude", "gemini_cli": "gemini", "chatgpt": "codex", "siwc": "codex"}


def provider_family(name: Any) -> str:
    n = str(name or "").strip().lower()
    return _FAMILY.get(n, n)


def _strict_from_env() -> bool:
    return (os.environ.get("LLM_POOL_STRICT") or "").strip().lower() in ("1", "true", "yes", "on")


class PoolPausedError(RuntimeError):
    """Every provider in the pool is paused (rate limited or failing); raised without calling any of them."""
    status_code = 429

    def __init__(self, retry_at: float):
        self.retry_at = retry_at
        super().__init__(f"Error code: 429 - all providers in the pool are paused for another "
                         f"{max(0, int(retry_at - time.time()))}s (rate limits or failures)")


@dataclass
class ProviderSlot:
    provider: str
    model: str
    base_url: str
    api_key: str = ""
    client: Any = None
    paused_until: float = 0.0
    pause_seconds: float = 60.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    rate_limits: int = 0
    timeouts: int = 0
    last_error: str = ""
    answered_by: Dict[str, int] = field(default_factory=dict)    # gateway backend that answered -> calls

    def is_healthy(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now >= self.paused_until

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "healthy": self.is_healthy(),
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "failures": self.failures,
            "rate_limits": self.rate_limits,
            "timeouts": self.timeouts,
            "last_error": self.last_error or None,
            "answered_by": dict(self.answered_by),
        }


class _BoundCompletions:
    def __init__(self, pool: "MultiProviderPool", preferred_index: Optional[int] = None):
        self._pool = pool
        self._preferred_index = preferred_index

    def create(self, **kwargs: Any) -> Any:
        return self._pool._create_completion(preferred_index=self._preferred_index, **kwargs)


class _BoundChat:
    def __init__(self, pool: "MultiProviderPool", preferred_index: Optional[int] = None):
        self.completions = _BoundCompletions(pool, preferred_index=preferred_index)


class BoundProviderClient:
    """View of a `MultiProviderPool` pinned to a preferred provider slot (with automatic failover)."""

    def __init__(self, pool: "MultiProviderPool", slot_index: int):
        self.pool = pool
        self.slot_index = slot_index % max(1, len(pool.slots))
        self.chat = _BoundChat(pool, preferred_index=self.slot_index)

    @property
    def slot(self) -> ProviderSlot:
        return self.pool.slots[self.slot_index]

    @property
    def base_url(self) -> str:
        return self.slot.base_url

    @property
    def provider(self) -> str:
        return self.slot.provider

    @property
    def model_name(self) -> str:
        return self.slot.model


class MultiProviderPool:
    """
    Thread-safe pool of OpenAI-compatible LLM clients across Claude, OpenAI/ChatGPT,
    Google Gemini, and local gateways/models.

    With more than one slot the SDK clients are built with max_retries=0: a rate limit, timeout or 5xx fails over
    to the next healthy slot at once instead of being retried (with backoff) against the same provider.
    """

    def __init__(self, slots: List[ProviderSlot], pause_seconds: float = 60.0,
                 client_options: Optional[Dict[str, Any]] = None, _parent: Optional["MultiProviderPool"] = None):
        if not slots:
            raise ValueError("MultiProviderPool requires at least one ProviderSlot")
        self.slots = slots
        self.pause_seconds = pause_seconds
        # a with_options() view shares the parent's slots, lock and counters (pauses and usage stay pool-wide)
        self._lock = _parent._lock if _parent is not None else threading.Lock()
        self._rr = 0
        self._client_options = dict(client_options or {})
        self._option_clients: Dict[int, Any] = {}
        # agent id -> slot: the provider that wrote a person also plays and answers for them (with_people)
        self._assign: Dict[Any, int] = dict(_parent._assign) if _parent is not None else {}
        # strict: a call bound to a slot never fails over to another provider (LLM_POOL_STRICT), so a person's
        # answers always come from their own model; failures are reported instead of substituted
        self.strict: bool = _parent.strict if _parent is not None else _strict_from_env()
        self.chat = _BoundChat(self, preferred_index=None)

    @property
    def is_multi(self) -> bool:
        return len(self.slots) > 1

    @property
    def base_url(self) -> str:
        return self.slots[0].base_url

    @property
    def provider(self) -> str:
        return self.slots[0].provider

    @property
    def model_name(self) -> str:
        return self.slots[0].model

    @property
    def providers(self) -> List[str]:
        return [s.provider for s in self.slots]

    def for_slot(self, index: int) -> BoundProviderClient:
        """Return a client view bound to slot `index % len(slots)`."""
        return BoundProviderClient(self, index % len(self.slots))

    def with_options(self, **options: Any) -> "MultiProviderPool":
        """A view of this pool whose SDK calls use `client.with_options(**options)`. Pauses and usage counters stay
        shared with this pool. In a multi-provider pool retries stay at 0 so failover happens at the pool level."""
        merged = {**self._client_options, **options}
        if self.is_multi:
            merged["max_retries"] = 0
        return MultiProviderPool(self.slots, pause_seconds=self.pause_seconds, client_options=merged, _parent=self)

    def _client_for(self, slot: ProviderSlot) -> Any:
        if not self._client_options or not hasattr(slot.client, "with_options"):
            return slot.client
        key = id(slot)
        client = self._option_clients.get(key)
        if client is None:
            client = slot.client.with_options(**self._client_options)
            self._option_clients[key] = client
        return client

    def slot_for_provider(self, provider: Any) -> Optional[int]:
        """Index of the slot that serves `provider` (claude_code and claude count as the same family)."""
        want = provider_family(provider)
        if not want:
            return None
        for i, s in enumerate(self.slots):
            if provider_family(s.provider) == want:
                return i
        return None

    def with_people(self, people: Any) -> "MultiProviderPool":
        """A view whose for_agent sends each person to the slot of the provider that wrote them (their
        model_provider), so one model writes, plays and answers for a person. Anyone else keeps agent_id % slots."""
        view = MultiProviderPool(self.slots, pause_seconds=self.pause_seconds, client_options=self._client_options,
                                 _parent=self)
        for p in people or []:
            if not isinstance(p, dict) or p.get("agent_id") is None:
                continue
            idx = self.slot_for_provider(p.get("model_provider"))
            if idx is not None:
                view._assign[p["agent_id"]] = idx
                view._assign[str(p["agent_id"])] = idx
        return view

    def for_agent(self, agent_id: Any) -> BoundProviderClient:
        """The slot of the provider that wrote this person (with_people), else a fixed slot by agent id."""
        if agent_id in self._assign:
            return BoundProviderClient(self, self._assign[agent_id])
        if isinstance(agent_id, int):
            idx = agent_id % len(self.slots)
        else:
            digest = hashlib.sha256(str(agent_id).encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % len(self.slots)
        return BoundProviderClient(self, idx)

    def _ordered_indices(self, preferred_index: Optional[int] = None) -> List[int]:
        n = len(self.slots)
        now = time.time()
        with self._lock:
            if preferred_index is None:
                start = self._rr % n
                self._rr += 1
            else:
                start = preferred_index % n
            order = [(start + offset) % n for offset in range(n)]
        healthy = [i for i in order if self.slots[i].is_healthy(now)]
        paused = [i for i in order if i not in healthy]
        return healthy + paused

    def _adapt_kwargs_for_slot(self, slot: ProviderSlot, kwargs: Dict[str, Any], is_failover: bool) -> Dict[str, Any]:
        from .openai_chat_compat import (CLAUDE_DEFAULT_MAX_TOKENS, JSON_PROMPT_HINT, fixed_sampling_target,
                                         is_claude_target, is_gemini_target, is_gpt5_family, json_mode_by_prompt)

        adapted = dict(kwargs)
        if not getattr(slot.client, "supports_cache_break", False):
            from .anthropic_native import strip_cache_break
            adapted["messages"] = strip_cache_break(adapted.get("messages") or [])
        req_model = str(adapted.get("model") or "").strip()
        # Use the slot's model when failing over, when no model was specified, or when the requested model
        # belongs to a different provider family than the slot.
        req_provider = canonical_provider(None, None, req_model) if req_model else slot.provider
        if is_failover or not req_model or (req_provider != slot.provider and slot.model):
            adapted["model"] = slot.model
        model = str(adapted.get("model") or slot.model)
        if is_gemini_target(slot.client or slot, model) and model.lower().startswith("models/"):
            model = model.split("/", 1)[1]
            adapted["model"] = model

        target = slot.client or slot
        claude = is_claude_target(target, model)
        gpt5 = is_gpt5_family(model)

        # Normalize response_format vs prompt JSON instruction when crossing between Claude/MiniMax and the others
        if "response_format" in adapted and json_mode_by_prompt(target, model):
            adapted.pop("response_format", None)
            msgs = list(adapted.get("messages") or [])
            if not msgs or JSON_PROMPT_HINT not in str(msgs[-1].get("content", "")):
                msgs.append({"role": "user", "content": JSON_PROMPT_HINT})
            adapted["messages"] = msgs
        if claude and "max_tokens" not in adapted and "max_completion_tokens" not in adapted:
            adapted["max_tokens"] = CLAUDE_DEFAULT_MAX_TOKENS
        if fixed_sampling_target(target, model):
            adapted.pop("temperature", None)
            adapted.pop("top_p", None)

        if gpt5:
            adapted.pop("temperature", None)
            if "max_tokens" in adapted:
                adapted["max_completion_tokens"] = adapted.pop("max_tokens")
        else:
            if "max_completion_tokens" in adapted and "max_tokens" not in adapted:
                adapted["max_tokens"] = adapted.pop("max_completion_tokens")

        return adapted

    def _wait_or_raise_if_all_paused(self) -> None:
        """Multi pool with every slot paused: wait for the first one to come back when that is soon, else fail fast
        instead of sending one more request to each paused provider."""
        if not self.is_multi:
            return
        now = time.time()
        with self._lock:
            if any(s.is_healthy(now) for s in self.slots):
                return
            resume = min(s.paused_until for s in self.slots)
        wait = resume - now
        if wait > MAX_WAIT_S:
            raise PoolPausedError(resume)
        time.sleep(max(0.0, wait))

    def _wait_for_slot(self, idx: int) -> None:
        wait = self.slots[idx].paused_until - time.time()
        if wait <= 0:
            return
        if wait > MAX_WAIT_S:
            raise PoolPausedError(self.slots[idx].paused_until)
        time.sleep(wait)

    def _create_completion(self, preferred_index: Optional[int] = None, **kwargs: Any) -> Any:
        if self.strict and self.is_multi and preferred_index is not None:
            idx = preferred_index % len(self.slots)
            self._wait_for_slot(idx)
            indices = [idx] * 3                         # the same provider, retried; never another one
        else:
            self._wait_or_raise_if_all_paused()
            indices = self._ordered_indices(preferred_index)
        now = time.time()
        if self.is_multi and not (self.strict and preferred_index is not None):
            healthy = [i for i in indices if self.slots[i].is_healthy(now)]
            indices = healthy or indices[:1]           # paused slots are not tried again until their pause ends
        last_error: Optional[Exception] = None
        for attempt, idx in enumerate(indices):
            slot = self.slots[idx]
            call_kwargs = self._adapt_kwargs_for_slot(slot, kwargs, is_failover=(attempt > 0 or (preferred_index is not None and idx != preferred_index)))
            try:
                resp = self._client_for(slot).chat.completions.create(**call_kwargs)
            except Exception as err:
                last_error = err
                is_rl = _is_rate_limit(err)
                transient = _is_rate_limit_or_transient(err)
                with self._lock:
                    slot.failures += 1
                    slot.last_error = type(err).__name__
                    if is_rl:
                        slot.rate_limits += 1
                        wait = _retry_after(err) or getattr(err, "retry_at", 0) and max(0.0, err.retry_at - time.time())
                        slot.paused_until = time.time() + max(float(wait or 0), slot.pause_seconds or self.pause_seconds)
                    elif transient:
                        if _is_timeout(err):
                            slot.timeouts += 1
                        if self.is_multi:
                            slot.paused_until = max(slot.paused_until, time.time() + TRANSIENT_PAUSE_S)
                if len(indices) > 1 and transient and attempt < len(indices) - 1:
                    if self.strict and preferred_index is not None:
                        if is_rl:
                            raise
                        time.sleep(min(2.0 * (attempt + 1), 6.0))
                    continue
                raise
            usage = getattr(resp, "usage", None)
            in_tok = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
            out_tok = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
            answered = answered_provider(resp) or slot.provider
            with self._lock:
                slot.calls += 1
                slot.input_tokens += in_tok
                slot.output_tokens += out_tok
                slot.answered_by[answered] = slot.answered_by.get(answered, 0) + 1
            try:
                # the provider that actually produced the answer: a multi gateway reports its backend per call
                setattr(resp, "_mm_provider", answered)
                setattr(resp, "_mm_slot_provider", slot.provider)
                setattr(resp, "_mm_model", getattr(resp, "model", None) if answered != slot.provider and getattr(resp, "model", None)
                        else (call_kwargs.get("model") or slot.model))
            except Exception:
                pass
            return resp
        if last_error is not None:
            raise last_error
        raise RuntimeError("No provider slots available in MultiProviderPool")

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            slots_info = [s.to_dict() for s in self.slots]
        by_provider: Dict[str, Dict[str, int]] = {}
        for s in slots_info:
            row = by_provider.setdefault(s["provider"], {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                         "failures": 0, "rate_limits": 0})
            for k in row:
                row[k] += int(s.get(k) or 0)
        return {
            "is_multi": self.is_multi,
            "providers": [s["provider"] for s in slots_info],
            "slots": slots_info,
            "by_provider": by_provider,
            "total_calls": sum(s["calls"] for s in slots_info),
            "total_input_tokens": sum(s["input_tokens"] for s in slots_info),
            "total_output_tokens": sum(s["output_tokens"] for s in slots_info),
            "total_rate_limits": sum(s["rate_limits"] for s in slots_info),
        }

    @classmethod
    def from_env(
        cls,
        env: Optional[Dict[str, str]] = None,
        client_factory: Optional[Callable[..., Any]] = None,
        primary_api_key: Optional[str] = None,
        primary_base_url: Optional[str] = None,
        primary_model: Optional[str] = None,
        primary_provider: Optional[str] = None,
    ) -> "MultiProviderPool":
        """
        Build a `MultiProviderPool` from environment variables (`LLM_POOL` or auto-discovered keys).

        Gateway providers (codex, antigravity, claude_code, gemini_cli) need `<NAME>_GATEWAY_URL` and
        `<NAME>_GATEWAY_KEY` (the token file of that gateway); `LLM_BASE_URL`/`LLM_API_KEY` are used for them only
        when `LLM_GATEWAY` names that same backend. They never use OPENAI_API_KEY.
        """
        env_map = dict(os.environ if env is None else env)
        retries: Dict[str, int] = {}
        if client_factory is None:
            from openai import OpenAI

            def client_factory(api_key, base_url, **kw):
                return OpenAI(api_key=api_key, base_url=base_url, **kw)
        factory = client_factory
        default_factory = client_factory is None or getattr(client_factory, "__name__", "") == "client_factory"

        def build(key: str, base_url: str) -> Any:
            # Claude with an API key: the native Messages API, so prompt caching works (anthropic_native.py)
            from .anthropic_native import AnthropicChatClient, is_anthropic_api, native_claude_available
            if default_factory and is_anthropic_api(base_url) and key and native_claude_available():
                return AnthropicChatClient(api_key=key, base_url=base_url, max_retries=retries.get("max_retries"))
            if retries:
                try:
                    return factory(api_key=key, base_url=base_url, **retries)
                except TypeError:                 # test factories that take only api_key/base_url
                    pass
            return factory(api_key=key, base_url=base_url)

        pool_spec = (env_map.get("LLM_POOL") or "").strip()
        specs: List[Dict[str, str]] = []

        if pool_spec:
            if pool_spec.startswith("["):
                try:
                    parsed = json.loads(pool_spec)
                    if isinstance(parsed, list):
                        specs = [p for p in parsed if isinstance(p, dict)]
                except ValueError:
                    specs = []
            elif pool_spec.lower() in ("auto", "all", "*"):
                for prov in ("claude", "openai", "gemini", *GATEWAY_PROVIDERS, *API_PROVIDERS):
                    specs.append({"provider": prov})
            else:
                for item in pool_spec.split(","):
                    part = item.strip()
                    if not part:
                        continue
                    if ":" in part:
                        prov, mod = part.split(":", 1)
                        specs.append({"provider": PROVIDER_ALIASES.get(prov.strip().lower(), prov.strip().lower()), "model": mod.strip()})
                    else:
                        specs.append({"provider": PROVIDER_ALIASES.get(part.lower(), part.lower())})

        llm_gateway = (env_map.get("LLM_GATEWAY") or "").strip().lower()
        llm_provider = (env_map.get("LLM_PROVIDER") or "").strip().lower()
        resolved: List[Dict[str, str]] = []
        for spec in specs:
            prov = PROVIDER_ALIASES.get(str(spec.get("provider") or "").strip().lower()) or \
                canonical_provider(spec.get("provider"), spec.get("base_url"), spec.get("model"), env=env_map)
            defaults = PROVIDER_DEFAULTS.get(prov, PROVIDER_DEFAULTS["openai"])
            key = spec.get("api_key") or ""
            base_url = spec.get("base_url") or ""
            if prov in GATEWAY_PROVIDERS:
                upper = prov.upper()
                same_gateway = llm_gateway in (defaults.get("gateway"), prov) or (prov == "codex" and llm_gateway in ("chatgpt", "siwc"))
                base_url = base_url or env_map.get(f"{upper}_GATEWAY_URL") or (env_map.get("LLM_BASE_URL", "") if same_gateway else "")
                key = key or env_map.get(f"{upper}_GATEWAY_KEY") or (env_map.get("LLM_API_KEY", "") if same_gateway else "")
                if not (key and base_url):
                    continue
            elif not key:
                if prov == "claude":
                    key = env_map.get("ANTHROPIC_API_KEY") or (env_map.get("LLM_API_KEY") if llm_provider in ("claude", "anthropic") else "") or ""
                elif prov in ("openai", "chatgpt"):
                    key = env_map.get("OPENAI_API_KEY") or env_map.get("CHATGPT_API_KEY") or (env_map.get("LLM_API_KEY") if llm_provider in ("openai", "chatgpt") and not llm_gateway else "") or ""
                elif prov == "gemini":
                    key = env_map.get("GEMINI_API_KEY") or env_map.get("GOOGLE_API_KEY") or (env_map.get("LLM_API_KEY") if llm_provider == "gemini" else "") or ""
                elif prov == "ollama":
                    key = "local"
                elif prov in API_PROVIDERS:
                    key = provider_api_key(prov, env_map) or (env_map.get("LLM_API_KEY") if llm_provider and
                                                              PROVIDER_ALIASES.get(llm_provider) == prov else "") or ""
            if not key and prov != "ollama":
                continue
            base_url = base_url or env_map.get(f"{prov.upper()}_BASE_URL") or defaults["base_url"]
            if not base_url and prov in API_PROVIDERS and llm_provider and PROVIDER_ALIASES.get(llm_provider) == prov:
                base_url = env_map.get("LLM_BASE_URL") or ""
            model = spec.get("model") or env_map.get(f"{prov.upper()}_MODEL_NAME") or defaults["model"]
            if not (base_url and model):
                continue                         # qwen without QWEN_BASE_URL, custom without its URL or model
            resolved.append({"provider": prov, "model": model, "base_url": base_url, "api_key": key})

        slots: List[ProviderSlot] = []
        seen = set()
        if len(resolved) > 1:
            retries["max_retries"] = 0           # the pool fails over; SDK retries would hammer the failing provider
        for r in resolved:
            sig = (r["provider"], r["base_url"], r["model"])
            if sig in seen:
                continue
            seen.add(sig)
            slots.append(ProviderSlot(provider=r["provider"], model=r["model"], base_url=r["base_url"],
                                      api_key=r["api_key"], client=build(r["api_key"], r["base_url"])))

        if not slots:
            retries.clear()
            base_url = primary_base_url or env_map.get("LLM_BASE_URL")
            prov = canonical_provider(
                primary_provider or env_map.get("LLM_PROVIDER", "claude"),
                base_url,
                primary_model or env_map.get("LLM_MODEL_NAME"),
                env=env_map,
            )
            defaults = PROVIDER_DEFAULTS.get(prov, PROVIDER_DEFAULTS["claude"])
            key = (
                primary_api_key
                or env_map.get("LLM_API_KEY")
                or (env_map.get("ANTHROPIC_API_KEY") if prov == "claude" else None)
                or (env_map.get("GEMINI_API_KEY") or env_map.get("GOOGLE_API_KEY") if prov == "gemini" else None)
                or (env_map.get("OPENAI_API_KEY") if prov == "openai" else None)
                or (provider_api_key(prov, env_map) if prov in API_PROVIDERS else None)
                or "local"
            )
            base_url = base_url or defaults["base_url"] or PROVIDER_DEFAULTS["claude"]["base_url"]
            model = primary_model or env_map.get("LLM_MODEL_NAME") or defaults["model"]
            slots.append(ProviderSlot(provider=prov, model=model, base_url=base_url, api_key=key,
                                      client=build(key, base_url)))

        return cls(slots)

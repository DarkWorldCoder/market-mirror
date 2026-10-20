"""
Multi-Provider Agent Pool (`MultiProviderPool`).

Allows MarketMirror to run Claude, OpenAI/ChatGPT, Google Gemini, and local models
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
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

PROVIDER_DEFAULTS: Dict[str, Dict[str, str]] = {
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
    "codex": {
        "base_url": "http://127.0.0.1:5055/v1",
        "model": "codex",
        "key_env": "LLM_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "llama3.2",
        "key_env": "",
    },
}

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
}


def canonical_provider(name: Optional[str], base_url: Optional[str] = None, model: Optional[str] = None) -> str:
    """Resolve a canonical provider name ('claude', 'openai', 'gemini', 'ollama', 'custom')."""
    raw = (name or "").strip().lower()
    if raw in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[raw]
    url = (base_url or "").strip().lower()
    mod = (model or "").strip().lower()
    if "anthropic.com" in url or mod.startswith("claude"):
        return "claude"
    if "generativelanguage.googleapis.com" in url or mod.startswith("gemini") or mod.startswith("models/gemini"):
        return "gemini"
    if "11434" in url or "1234" in url:
        return "ollama"
    if "openai.com" in url or mod.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return raw or "openai"


def _is_rate_limit_or_transient(err: Exception) -> bool:
    status = getattr(err, "status_code", None) or getattr(err, "status", None)
    if status in (429, 500, 502, 503, 504, 529):
        return True
    text = str(err).lower()
    return any(
        token in text
        for token in (
            "429",
            "rate limit",
            "rate_limit",
            "quota",
            "too many requests",
            "overloaded",
            "resource_exhausted",
            "temporarily unavailable",
        )
    )


def _is_rate_limit(err: Exception) -> bool:
    status = getattr(err, "status_code", None) or getattr(err, "status", None)
    if status == 429:
        return True
    text = str(err).lower()
    return any(token in text for token in ("429", "rate limit", "rate_limit", "quota", "too many requests", "resource_exhausted"))


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
    """

    def __init__(self, slots: List[ProviderSlot], pause_seconds: float = 60.0):
        if not slots:
            raise ValueError("MultiProviderPool requires at least one ProviderSlot")
        self.slots = slots
        self.pause_seconds = pause_seconds
        self._lock = threading.Lock()
        self._rr = 0
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
        """Return a shallow pool clone where each underlying OpenAI client has `.with_options(**options)` applied."""
        new_slots: List[ProviderSlot] = []
        for s in self.slots:
            cl = s.client.with_options(**options) if hasattr(s.client, "with_options") else s.client
            new_slots.append(
                ProviderSlot(
                    provider=s.provider,
                    model=s.model,
                    base_url=s.base_url,
                    api_key=s.api_key,
                    client=cl,
                    paused_until=s.paused_until,
                    pause_seconds=s.pause_seconds,
                )
            )
        return MultiProviderPool(new_slots, pause_seconds=self.pause_seconds)

    def for_agent(self, agent_id: Any) -> BoundProviderClient:
        """Deterministically assign an agent ID to a provider slot in the pool."""
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
        from .openai_chat_compat import CLAUDE_DEFAULT_MAX_TOKENS, is_claude_target, is_gemini_target, is_gpt5_family

        adapted = dict(kwargs)
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

        claude = is_claude_target(slot.client or slot, model)
        gpt5 = is_gpt5_family(model)

        # Normalize response_format vs prompt JSON instruction when crossing between Claude and OpenAI/Gemini
        if claude and "response_format" in adapted:
            adapted.pop("response_format", None)
            msgs = list(adapted.get("messages") or [])
            json_hint = "Respond with a single valid JSON object only. No markdown fences, no extra text."
            if not msgs or json_hint not in str(msgs[-1].get("content", "")):
                msgs.append({"role": "user", "content": json_hint})
            adapted["messages"] = msgs
        if claude and "max_tokens" not in adapted and "max_completion_tokens" not in adapted:
            adapted["max_tokens"] = CLAUDE_DEFAULT_MAX_TOKENS

        if gpt5:
            adapted.pop("temperature", None)
            if "max_tokens" in adapted:
                adapted["max_completion_tokens"] = adapted.pop("max_tokens")
        else:
            if "max_completion_tokens" in adapted and "max_tokens" not in adapted:
                adapted["max_tokens"] = adapted.pop("max_completion_tokens")

        return adapted

    def _create_completion(self, preferred_index: Optional[int] = None, **kwargs: Any) -> Any:
        indices = self._ordered_indices(preferred_index)
        last_error: Optional[Exception] = None
        for attempt, idx in enumerate(indices):
            slot = self.slots[idx]
            call_kwargs = self._adapt_kwargs_for_slot(slot, kwargs, is_failover=(attempt > 0 or (preferred_index is not None and idx != preferred_index)))
            try:
                resp = slot.client.chat.completions.create(**call_kwargs)
                usage = getattr(resp, "usage", None)
                in_tok = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
                out_tok = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
                with self._lock:
                    slot.calls += 1
                    slot.input_tokens += in_tok
                    slot.output_tokens += out_tok
                try:
                    setattr(resp, "_mm_provider", slot.provider)
                    setattr(resp, "_mm_model", call_kwargs.get("model") or slot.model)
                except Exception:
                    pass
                return resp
            except Exception as err:
                last_error = err
                is_rl = _is_rate_limit(err)
                with self._lock:
                    slot.failures += 1
                    if is_rl:
                        slot.rate_limits += 1
                        slot.paused_until = time.time() + (slot.pause_seconds or self.pause_seconds)
                if len(indices) > 1 and _is_rate_limit_or_transient(err):
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("No provider slots available in MultiProviderPool")

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            slots_info = [s.to_dict() for s in self.slots]
        return {
            "is_multi": self.is_multi,
            "providers": [s["provider"] for s in slots_info],
            "slots": slots_info,
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
        """
        env_map = dict(os.environ if env is None else env)
        if client_factory is None:
            from openai import OpenAI
            client_factory = lambda api_key, base_url: OpenAI(api_key=api_key, base_url=base_url)

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
                for prov in ("claude", "openai", "gemini"):
                    specs.append({"provider": prov})
            else:
                for item in pool_spec.split(","):
                    part = item.strip()
                    if not part:
                        continue
                    if ":" in part:
                        prov, mod = part.split(":", 1)
                        specs.append({"provider": canonical_provider(prov), "model": mod.strip()})
                    else:
                        specs.append({"provider": canonical_provider(part)})

        slots: List[ProviderSlot] = []
        seen = set()

        for spec in specs:
            prov = canonical_provider(spec.get("provider"), spec.get("base_url"), spec.get("model"))
            defaults = PROVIDER_DEFAULTS.get(prov, PROVIDER_DEFAULTS["openai"])
            key = spec.get("api_key") or ""
            if not key:
                if prov == "claude":
                    key = env_map.get("ANTHROPIC_API_KEY") or (env_map.get("LLM_API_KEY") if canonical_provider(env_map.get("LLM_PROVIDER")) == "claude" else "") or ""
                elif prov in ("openai", "chatgpt"):
                    key = env_map.get("OPENAI_API_KEY") or env_map.get("CHATGPT_API_KEY") or (env_map.get("LLM_API_KEY") if canonical_provider(env_map.get("LLM_PROVIDER")) in ("openai", "chatgpt") else "") or ""
                elif prov == "codex":
                    key = env_map.get("CODEX_API_KEY") or env_map.get("OPENAI_API_KEY") or (env_map.get("LLM_API_KEY") if canonical_provider(env_map.get("LLM_PROVIDER")) == "codex" or env_map.get("LLM_GATEWAY") in ("codex", "chatgpt", "multi") else "") or ""
                elif prov == "gemini":
                    key = env_map.get("GEMINI_API_KEY") or env_map.get("GOOGLE_API_KEY") or (env_map.get("LLM_API_KEY") if canonical_provider(env_map.get("LLM_PROVIDER")) == "gemini" else "") or ""
                elif prov == "ollama":
                    key = "local"
            if not key and prov != "ollama":
                continue
            base_url = spec.get("base_url") or env_map.get(f"{prov.upper()}_BASE_URL") or defaults["base_url"]
            model = spec.get("model") or env_map.get(f"{prov.upper()}_MODEL_NAME") or defaults["model"]
            sig = (prov, base_url, model)
            if sig in seen:
                continue
            seen.add(sig)
            slots.append(
                ProviderSlot(
                    provider=prov,
                    model=model,
                    base_url=base_url,
                    api_key=key,
                    client=client_factory(api_key=key, base_url=base_url),
                )
            )

        if not slots:
            prov = canonical_provider(
                primary_provider or env_map.get("LLM_PROVIDER", "claude"),
                primary_base_url or env_map.get("LLM_BASE_URL"),
                primary_model or env_map.get("LLM_MODEL_NAME"),
            )
            defaults = PROVIDER_DEFAULTS.get(prov, PROVIDER_DEFAULTS["claude"])
            key = (
                primary_api_key
                or env_map.get("LLM_API_KEY")
                or (env_map.get("ANTHROPIC_API_KEY") if prov == "claude" else None)
                or (env_map.get("GEMINI_API_KEY") or env_map.get("GOOGLE_API_KEY") if prov == "gemini" else None)
                or (env_map.get("OPENAI_API_KEY") if prov == "openai" else None)
                or "local"
            )
            base_url = primary_base_url or env_map.get("LLM_BASE_URL") or defaults["base_url"]
            model = primary_model or env_map.get("LLM_MODEL_NAME") or defaults["model"]
            slots.append(
                ProviderSlot(
                    provider=prov,
                    model=model,
                    base_url=base_url,
                    api_key=key,
                    client=client_factory(api_key=key, base_url=base_url),
                )
            )

        return cls(slots)

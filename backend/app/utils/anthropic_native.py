"""
anthropic_native.py - Claude through the native Messages API (the official `anthropic` SDK), so prompt caching works.

The rest of MarketMirror speaks the OpenAI chat-completions shape to every provider. Anthropic's OpenAI-compatible
endpoint does not support prompt caching, so with an ANTHROPIC_API_KEY every call paid full price for the same brief,
context, rules and schema again and again. This client keeps the OpenAI-shaped interface the code already uses
(`client.chat.completions.create(model=..., messages=[...], max_tokens=...)`) and sends a native request:

- the system prompt becomes a system block with a cache breakpoint;
- a user message that contains CACHE_BREAK is split there: the shared part before it (brief, context, rules, schema)
  is one cached block, the per-person part after it is not. Many calls that share the first part then read it from
  the cache (about 0.1x the input price) instead of paying for it again. Without the marker no breakpoint is placed
  on the user message: a prompt that ends in unique content would only pay the cache-write premium;
- `temperature`/`top_p` are not sent (current Claude models reject non-default sampling values);
- effort comes from MM_CLAUDE_EFFORT (default low: writing people needs no long reasoning), unset to use the model's;
- the response is returned in the OpenAI shape, with usage.prompt_tokens counting cached and uncached input and the
  cache reads and writes reported as usage.cache_read_input_tokens / usage.cache_creation_input_tokens.

A refusal (stop_reason "refusal") is raised as an error, so the caller counts that call as failed.
"""

from __future__ import annotations

import os
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

# the marker prompts put between their shared part and the per-person part (stripped for every other provider)
CACHE_BREAK = "\n<<<MM_CACHE_BREAK>>>\n"

CACHE_TTL = (os.environ.get("MM_CACHE_TTL") or "").strip()          # "" = 5 minutes (default), or "1h"


def strip_cache_break(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The messages without the marker, for providers that do not cache this way (text and multi-part content)."""
    out = []
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, str) and CACHE_BREAK in c:
            m = {**m, "content": c.replace(CACHE_BREAK, "\n")}
        elif isinstance(c, list) and any(isinstance(p, dict) and CACHE_BREAK in str(p.get("text") or "") for p in c):
            m = {**m, "content": [{**p, "text": p["text"].replace(CACHE_BREAK, "\n")}
                                  if isinstance(p, dict) and isinstance(p.get("text"), str) else p for p in c]}
        out.append(m)
    return out


_DATA_URI = re.compile(r"^data:(image/[\w.+-]+);base64,(.+)$", re.S)


def _image_block(part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An OpenAI image_url part -> a native image block (base64 data URI or https URL)."""
    iu = part.get("image_url")
    url = iu.get("url") if isinstance(iu, dict) else iu
    if not isinstance(url, str):
        return None
    m = _DATA_URI.match(url)
    if m:
        return {"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}}
    if url.startswith("https://"):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _parts_to_native(parts: List[Any]) -> Tuple[List[Dict[str, Any]], bool]:
    """Multi-part user content -> native blocks. A text part that starts with the cache marker puts the breakpoint
    on the block before it (e.g. shared instructions + an ad image, then the per-person part). Returns
    (blocks, marked)."""
    blocks: List[Dict[str, Any]] = []
    marked = False
    for p in parts or []:
        if isinstance(p, str):
            p = {"type": "text", "text": p}
        if not isinstance(p, dict):
            continue
        if p.get("type") == "image_url":
            b = _image_block(p)
            if b:
                blocks.append(b)
            continue
        text = str(p.get("text") or "")
        if CACHE_BREAK in text:
            head, _, tail = text.partition(CACHE_BREAK)
            if head.strip():
                blocks.append({"type": "text", "text": head})
            if blocks and not marked:
                blocks[-1]["cache_control"] = _cache_control()
                marked = True
            text = tail.replace(CACHE_BREAK, "\n")
        if text.strip():
            blocks.append({"type": "text", "text": text})
    return blocks, marked


def _cache_control() -> Dict[str, Any]:
    return {"type": "ephemeral", **({"ttl": CACHE_TTL} if CACHE_TTL in ("1h", "5m") else {})}


def _to_native(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """OpenAI-style messages -> (system blocks, native messages) with cache breakpoints."""
    system: List[Dict[str, Any]] = []
    native: List[Dict[str, Any]] = []
    for m in messages or []:
        role, content = m.get("role"), m.get("content")
        if role == "user" and isinstance(content, list) and any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            blocks, _ = _parts_to_native(content)
            native.append({"role": "user", "content": blocks})
            continue
        text = content if isinstance(content, str) else "".join(
            p.get("text", "") for p in content or [] if isinstance(p, dict))
        if role == "system":
            if text.strip():
                system.append({"type": "text", "text": text.replace(CACHE_BREAK, "\n")})
            continue
        role = "assistant" if role == "assistant" else "user"
        if role == "user" and CACHE_BREAK in text:
            shared, _, tail = text.partition(CACHE_BREAK)
            blocks = [{"type": "text", "text": shared, "cache_control": _cache_control()}]
            if tail.strip():
                blocks.append({"type": "text", "text": tail})
            native.append({"role": role, "content": blocks})
        else:
            native.append({"role": role, "content": text.replace(CACHE_BREAK, "\n")})
    if system and not any(isinstance(b, dict) and "cache_control" in b for m in native
                          for b in (m["content"] if isinstance(m["content"], list) else [])):
        system[-1]["cache_control"] = _cache_control()       # at least the instructions are reused
    return system, native


class _Completions:
    def __init__(self, owner: "AnthropicChatClient"):
        self._owner = owner

    def create(self, **kw: Any) -> Any:
        return self._owner._create(**kw)


class AnthropicChatClient:
    """An OpenAI-shaped client for Claude on the native Messages API, with prompt caching."""

    supports_cache_break = True

    def __init__(self, api_key: str, base_url: Optional[str] = None, timeout: Optional[float] = None,
                 max_retries: Optional[int] = None, effort: Optional[str] = None, _client: Any = None):
        if _client is None:
            import anthropic
            kwargs: Dict[str, Any] = {"api_key": api_key}
            if timeout is not None:
                kwargs["timeout"] = timeout
            if max_retries is not None:
                kwargs["max_retries"] = max_retries
            _client = anthropic.Anthropic(**kwargs)
        self._client = _client
        self.api_key = api_key
        self.base_url = base_url or "https://api.anthropic.com/v1/"
        self.effort = (os.environ.get("MM_CLAUDE_EFFORT", "low") if effort is None else effort).strip().lower()
        self.chat = SimpleNamespace(completions=_Completions(self))

    def with_options(self, **options: Any) -> "AnthropicChatClient":
        """Same client with SDK options (timeout, max_retries), as the OpenAI client offers."""
        inner = self._client.with_options(**{k: v for k, v in options.items() if k in ("timeout", "max_retries")})
        return AnthropicChatClient(self.api_key, self.base_url, effort=self.effort, _client=inner)

    def _create(self, model: str, messages: List[Dict[str, Any]], max_tokens: Optional[int] = None,
                max_completion_tokens: Optional[int] = None, **_ignored: Any) -> Any:
        system, native = _to_native(messages)
        params: Dict[str, Any] = {"model": model, "max_tokens": int(max_tokens or max_completion_tokens or 8192),
                                  "messages": native}
        if system:
            params["system"] = system
        if self.effort in ("low", "medium", "high", "xhigh", "max"):
            params["output_config"] = {"effort": self.effort}
        msg = self._client.messages.create(**params)
        if getattr(msg, "stop_reason", None) == "refusal":
            raise RuntimeError(f"Claude declined the request (refusal: {getattr(getattr(msg, 'stop_details', None), 'category', None)})")
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        u = msg.usage
        read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
        write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        uncached = int(getattr(u, "input_tokens", 0) or 0)
        usage = SimpleNamespace(prompt_tokens=uncached + read + write, completion_tokens=int(u.output_tokens or 0),
                                total_tokens=uncached + read + write + int(u.output_tokens or 0),
                                prompt_tokens_details=SimpleNamespace(cached_tokens=read),
                                cache_read_input_tokens=read, cache_creation_input_tokens=write,
                                uncached_input_tokens=uncached)
        return SimpleNamespace(id=msg.id, model=msg.model, usage=usage,
                               choices=[SimpleNamespace(index=0, finish_reason=msg.stop_reason,
                                                        message=SimpleNamespace(role="assistant", content=text))])


def native_claude_available() -> bool:
    if (os.environ.get("MM_CLAUDE_NATIVE") or "").strip().lower() in ("0", "false", "off", "no"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def is_anthropic_api(base_url: Optional[str]) -> bool:
    return "api.anthropic.com" in str(base_url or "")

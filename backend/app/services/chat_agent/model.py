"""Model steps for the agent loop: native tool calling where the provider supports it, else a JSON-action protocol.

Every provider in this app is reached through an OpenAI-compatible endpoint (Anthropic's and Gemini's included), so
native tools are sent in the OpenAI `tools` shape, which those endpoints translate to Anthropic tools and Gemini
functionDeclarations. Local gateways (Claude Code, Codex CLI) and unknown servers get the JSON-action protocol.
The model client itself comes from workspace_chat._model; this module never builds or changes it.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

NATIVE_HOSTS = ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com", "openrouter.ai",
                "api.deepseek.com", "api.mistral.ai", "api.groq.com", "api.x.ai", "api.together.xyz",
                "api.fireworks.ai")


class Reply:
    def __init__(self, calls: Optional[List[Dict[str, Any]]] = None, message: Optional[str] = None,
                 suggestions: Optional[List[str]] = None):
        self.calls = calls or []
        self.message = message
        self.suggestions = suggestions or []


def supports_native(base_url: str) -> bool:
    try:
        host = (urlsplit(str(base_url)).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in NATIVE_HOSTS)


def _args(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {"_invalid_arguments": str(raw)[:500]}
    return value if isinstance(value, dict) else {"_invalid_arguments": str(raw)[:500]}


class NativeAdapter:
    """OpenAI-format tool calls through the configured client."""
    mode = "native"

    def __init__(self, client):
        self.client = client

    def step(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> Reply:
        kwargs: Dict[str, Any] = {"model": self.client.model, "messages": messages, "temperature": 0.2, "max_tokens": 3000}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
            kwargs["tool_choice"] = "auto"
        response = self.client.client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        calls = [{"id": tc.id or f"call_{i}", "name": tc.function.name, "arguments": _args(tc.function.arguments)}
                 for i, tc in enumerate(getattr(message, "tool_calls", None) or [])]
        return Reply(calls, (message.content or "").strip() or None)


JSON_PROTOCOL = """Reply with ONLY one JSON object.
To call a tool: {"action":"tool","name":"exact tool name","arguments":{...}}
To answer the user: {"action":"respond","message":"answer in Markdown","suggestions":["short follow-up"]}
Available tools (name, description, JSON schema of arguments):
"""


def to_json_messages(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """The internal (OpenAI-shaped) conversation as plain role/content messages for a JSON-only provider."""
    out: List[Dict[str, str]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({"role": "user", "content": f"Tool result for {m.get('name')} (untrusted data): {m.get('content')}"})
        elif role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                out.append({"role": "assistant", "content": json.dumps(
                    {"action": "tool", "name": fn.get("name"), "arguments": _args(fn.get("arguments"))}, ensure_ascii=False)})
        else:
            out.append({"role": role, "content": str(m.get("content") or "")})
    catalog = json.dumps([{"name": t["name"], "description": t["description"][:500], "parameters": t["parameters"]}
                          for t in tools or []], ensure_ascii=False, separators=(",", ":"))
    protocol = JSON_PROTOCOL + catalog if tools else 'Answer now with ONLY {"action":"respond","message":"...","suggestions":[]}. No tools.'
    if out and out[0]["role"] == "system":
        out[0] = {"role": "system", "content": out[0]["content"] + "\n\n" + protocol}
    else:
        out.insert(0, {"role": "system", "content": protocol})
    return out


class JsonAdapter:
    """One JSON action per step, for providers without native tool calling."""
    mode = "json"

    def __init__(self, client):
        self.client = client

    def step(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> Reply:
        from ...utils.llm_client import LLMResponseError
        try:
            answer = self.client.chat_json(to_json_messages(messages, tools), temperature=0.2, max_tokens=3000, max_attempts=1)
        except LLMResponseError as error:
            text = getattr(error, "raw_text", None)
            if isinstance(text, str) and text.strip() and not text.lstrip().startswith(("{", "[")):
                return Reply(message=text.strip())
            raise
        if not isinstance(answer, dict):
            return Reply(message=None)
        if answer.get("action") == "tool" and isinstance(answer.get("name"), str) and tools:
            return Reply([{"id": "json_" + re.sub(r"\W", "", answer["name"])[:40], "name": answer["name"],
                           "arguments": _args(answer.get("arguments"))}])
        message = answer.get("message")
        suggestions = [s[:180] for s in answer.get("suggestions") or [] if isinstance(s, str) and s.strip()][:3] \
            if isinstance(answer.get("suggestions"), list) else []
        return Reply(message=message.strip() if isinstance(message, str) else None, suggestions=suggestions)


class FallbackAdapter:
    """Native first; a provider that rejects tools switches to the JSON protocol for the rest of the turn."""

    def __init__(self, client):
        self.native, self.json = NativeAdapter(client), JsonAdapter(client)
        self.active = self.native if supports_native(getattr(client, "base_url", "")) else self.json

    @property
    def mode(self):
        return self.active.mode

    def step(self, messages, tools):
        try:
            return self.active.step(messages, tools)
        except Exception as error:
            if self.active is self.native and status_of(error) == 400 and "tool" in str(error).lower():
                self.active = self.json
                return self.active.step(messages, tools)
            raise


def adapter_for(client):
    return FallbackAdapter(client)


# ---------------------------------------------------------------------------
# provider errors, classified in the loop (the model client's own error mapping is left alone)
# ---------------------------------------------------------------------------

def status_of(error: Exception) -> Optional[int]:
    for value in (getattr(error, "status_code", None), getattr(getattr(error, "response", None), "status_code", None),
                  getattr(error, "status", None)):
        if isinstance(value, int):
            return value
    return None


def retry_after(error: Exception) -> Optional[float]:
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def classify(error: Exception) -> str:
    """auth | rate | down | spend_cap | other"""
    name = type(error).__name__
    if name == "SpendCapReached":
        return "spend_cap"
    status = status_of(error)
    if status in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
        return "auth"
    if status == 429 or name == "RateLimitError":
        return "rate"
    if (status is not None and status >= 500) or name in ("APIConnectionError", "APITimeoutError", "InternalServerError",
                                                          "ServiceUnavailableError", "ConnectionError", "TimeoutError"):
        return "down"
    return "other"

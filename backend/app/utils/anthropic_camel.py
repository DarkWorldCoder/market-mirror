"""
anthropic_camel.py - a camel model backend that plays OASIS agents on Claude's native Messages API, so prompt caching
works inside the social rounds, the buyer survey and the sales pitch.

OASIS agents are camel ChatAgents. With an ANTHROPIC_API_KEY they used to go through Anthropic's OpenAI-compatible
endpoint, which does not cache, so every round and every interview paid full price again for the same tool list,
the same persona system prompt and the same memory. `ClaudeNativeModel` keeps camel's contract (OpenAI-style
messages and tool schemas in, an OpenAI `ChatCompletion` out, sync `run` and async `arun`) and sends a native request:

- tools: OpenAI function schemas become Anthropic tools; the last tool carries a cache breakpoint. The tool list is
  identical for every agent on a platform, so one entry serves the whole crowd;
- system: the agent's system prompt (persona + OASIS instructions) is a system block with a breakpoint. Leading system
  messages are joined (an exact repeat, as OASIS interviews send, is dropped); a system message later in the history
  becomes user text;
- the conversation: with tools (a social action) top-level automatic caching follows the growing memory, so the next
  call in the round and the agent's next round read it back; without tools (an interview) the final question is
  one-off, so the breakpoint goes on the last message before it and the agent's later interviews read the memory;
- assistant tool calls become tool_use blocks and tool messages tool_result blocks, grouped the way the Messages API
  requires; a call without a recorded result gets a placeholder result and a result without its call is dropped;
- effort comes from OASIS_CLAUDE_EFFORT, else MM_CLAUDE_EFFORT (default low); thinking is left at the model default;
- TTL comes from OASIS_CACHE_TTL, else MM_CACHE_TTL ("" = 5 minutes, or "1h"); every breakpoint uses it.

Usage is returned in the OpenAI shape (prompt_tokens counts cached and uncached input, prompt_tokens_details.
cached_tokens the reads) plus cache_read_input_tokens / cache_creation_input_tokens, and every call is added to a
process-wide meter per usage tag (the runner tags each platform's models and writes the per-round deltas to
claude_cache_usage.json). A refusal is raised as an error, like the direct client does.

MM_CLAUDE_NATIVE=off turns this off (the OpenAI-compatible endpoint is used again).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from camel.models.openai_compatible_model import OpenAICompatibleModel
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function
from openai.types.completion_usage import CompletionUsage, PromptTokensDetails

from .anthropic_native import effort_supported, is_anthropic_api, native_claude_available

_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length",
           "pause_turn": "stop", "refusal": "content_filter"}
_ID_OK = re.compile(r"[^a-zA-Z0-9_-]")
NO_RESULT = "No result was recorded for this action."


def cache_ttl() -> str:
    v = (os.environ.get("OASIS_CACHE_TTL") or os.environ.get("MM_CACHE_TTL") or "").strip().lower()
    return v if v in ("1h", "5m") else ""


def agent_effort() -> str:
    v = os.environ.get("OASIS_CLAUDE_EFFORT")
    if v is None:
        v = os.environ.get("MM_CLAUDE_EFFORT", "low")
    return v.strip().lower()


def _cache_control(ttl: Optional[str] = None) -> Dict[str, Any]:
    ttl = cache_ttl() if ttl is None else ttl
    return {"type": "ephemeral", **({"ttl": ttl} if ttl else {})}


# ---------------------------------------------------------------------------------------------------
# Usage meter
# ---------------------------------------------------------------------------------------------------

_FIELDS = ("calls", "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
_LOCK = threading.Lock()
_USAGE: Dict[str, Dict[str, int]] = {}
_MARKS: Dict[str, Dict[str, int]] = {}


def _add_usage(tag: str, uncached: int, read: int, write: int, output: int) -> None:
    with _LOCK:
        row = _USAGE.setdefault(tag, dict.fromkeys(_FIELDS, 0))
        row["calls"] += 1
        row["input_tokens"] += uncached
        row["cache_read_input_tokens"] += read
        row["cache_creation_input_tokens"] += write
        row["output_tokens"] += output


def usage_totals(tag: Optional[str] = None) -> Dict[str, int]:
    """Totals for one tag, or for all tags together."""
    with _LOCK:
        rows = [_USAGE[tag]] if tag is not None and tag in _USAGE else ([] if tag is not None else list(_USAGE.values()))
        return {f: sum(r[f] for r in rows) for f in _FIELDS}


def usage_since_mark(tag: str) -> Dict[str, int]:
    """What `tag` used since the previous call of this function (the first call counts from the start)."""
    now = usage_totals(tag)
    with _LOCK:
        prev = _MARKS.get(tag) or dict.fromkeys(_FIELDS, 0)
        _MARKS[tag] = now
    return {f: now[f] - prev[f] for f in _FIELDS}


def reset_usage() -> None:
    with _LOCK:
        _USAGE.clear()
        _MARKS.clear()


def record_stage(simulation_dir: Optional[str], tag: str, stage: str, log: Any = None) -> Optional[Dict[str, Any]]:
    """Append what `tag` used since its last stage to <simulation_dir>/claude_cache_usage.json and log one line.
    Does nothing when no native Claude call was made under `tag`."""
    delta = usage_since_mark(tag)
    if not delta["calls"]:
        return None
    row = {"platform": tag, "stage": stage, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **delta}
    fresh = delta["input_tokens"] + delta["cache_read_input_tokens"] + delta["cache_creation_input_tokens"]
    row["cache_read_share"] = round(delta["cache_read_input_tokens"] / fresh, 4) if fresh else 0.0
    if log:
        log(f"Claude cache {stage}: {delta['calls']} calls, read {delta['cache_read_input_tokens']:,}, "
            f"written {delta['cache_creation_input_tokens']:,}, uncached {delta['input_tokens']:,}, "
            f"output {delta['output_tokens']:,} tokens")
    if simulation_dir:
        path = os.path.join(simulation_dir, "claude_cache_usage.json")
        with _LOCK:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            stages = list(data.get("stages") or []) + [row]
            totals = {f: sum(int(s.get(f) or 0) for s in stages) for f in _FIELDS}
            data = {"ttl": cache_ttl() or "5m", "stages": stages, "totals": totals}
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
    return row


def tag_models(agent_graph: Any, tag: str) -> int:
    """Set the usage tag on every ClaudeNativeModel behind the agents of `agent_graph` (shared or per agent)."""
    seen, n = set(), 0
    try:
        agents = [a for _, a in agent_graph.get_agents()]
    except Exception:  # noqa: BLE001
        agents = []
    for agent in agents:
        backend = getattr(agent, "model_backend", None)
        for m in list(getattr(backend, "models", None) or [backend]):
            if isinstance(m, ClaudeNativeModel) and id(m) not in seen:
                seen.add(id(m))
                m.usage_tag = tag
                n += 1
    return n


# ---------------------------------------------------------------------------------------------------
# OpenAI shapes -> Messages API
# ---------------------------------------------------------------------------------------------------

def _tool_id(raw: Any) -> str:
    return _ID_OK.sub("_", str(raw or "")) or "call"


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content or [] if isinstance(p, dict) and p.get("type", "text") == "text")


def _user_blocks(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, str) or content is None:
        return [{"type": "text", "text": content}] if (content or "").strip() else []
    out: List[Dict[str, Any]] = []
    for p in content:
        if isinstance(p, str):
            if p.strip():
                out.append({"type": "text", "text": p})
        elif isinstance(p, dict) and p.get("type") == "image_url":
            url = str((p.get("image_url") or {}).get("url") or "")
            m = re.match(r"data:(image/[\w.+-]+);base64,(.*)$", url, re.S)
            out.append({"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}}
                       if m else {"type": "image", "source": {"type": "url", "url": url}})
        elif isinstance(p, dict) and str(p.get("text") or "").strip():
            out.append({"type": "text", "text": p["text"]})
    return out


def tools_to_native(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """OpenAI function schemas -> Anthropic tool definitions (same order, so the prefix stays byte-stable)."""
    out = []
    for t in tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        if not fn.get("name"):
            continue
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        tool = {"name": fn["name"], "input_schema": params}
        if fn.get("description"):
            tool["description"] = fn["description"]
        out.append(tool)
    return out


def messages_to_native(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """camel's OpenAI-style messages -> (system blocks, native messages), without cache breakpoints."""
    system: List[Dict[str, Any]] = []
    native: List[Dict[str, Any]] = []

    def add(role: str, blocks: List[Dict[str, Any]]) -> None:
        if not blocks:
            return
        if native and native[-1]["role"] == role:
            native[-1]["content"].extend(blocks)
        else:
            native.append({"role": role, "content": list(blocks)})

    open_calls: set = set()          # tool_use ids of the latest assistant turn still waiting for a result
    for m in messages or []:
        role = m.get("role")
        if role in ("system", "developer"):
            text = _text_of(m.get("content"))
            if not text.strip():
                continue
            if not native:
                if not system or system[-1]["text"] != text:
                    system.append({"type": "text", "text": text})
            else:
                add("user", [{"type": "text", "text": text}])
            continue
        if role == "assistant":
            blocks: List[Dict[str, Any]] = []
            text = _text_of(m.get("content"))
            if text.strip():
                blocks.append({"type": "text", "text": text.rstrip()})
            calls = []
            for c in m.get("tool_calls") or []:
                fn = (c.get("function") if isinstance(c, dict) else getattr(c, "function", None)) or {}
                name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
                args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", None)
                cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                try:
                    data = json.loads(args) if isinstance(args, str) else (args or {})
                except ValueError:
                    data = {"raw": args}
                if not isinstance(data, dict):
                    data = {"value": data}
                calls.append({"type": "tool_use", "id": _tool_id(cid), "name": str(name or "action"), "input": data})
            add("assistant", blocks + calls)
            open_calls = {c["id"] for c in calls} if calls else set()
            continue
        if role in ("tool", "function"):
            cid = _tool_id(m.get("tool_call_id"))
            if cid not in open_calls:
                continue                     # its call is gone (windowed memory): the API would reject it
            open_calls.discard(cid)
            result = m.get("content")
            result = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            add("user", [{"type": "tool_result", "tool_use_id": cid, "content": result or "(empty)"}])
            continue
        add("user", _user_blocks(m.get("content")))

    # every tool_use needs its tool_result at the start of the next user message
    i = 0
    while i < len(native):
        msg = native[i]
        if msg["role"] == "assistant":
            ids = [b["id"] for b in msg["content"] if b.get("type") == "tool_use"]
            nxt = native[i + 1] if i + 1 < len(native) and native[i + 1]["role"] == "user" else None
            have = {b.get("tool_use_id") for b in (nxt["content"] if nxt else []) if b.get("type") == "tool_result"}
            missing = [x for x in ids if x not in have]
            if missing:
                fill = [{"type": "tool_result", "tool_use_id": x, "content": NO_RESULT} for x in missing]
                if nxt is None:
                    native.insert(i + 1, {"role": "user", "content": fill})
                else:
                    results = [b for b in nxt["content"] if b.get("type") == "tool_result"]
                    rest = [b for b in nxt["content"] if b.get("type") != "tool_result"]
                    nxt["content"] = results + fill + rest
        i += 1
    if native and native[0]["role"] != "user":
        native.insert(0, {"role": "user", "content": [{"type": "text", "text": "(The conversation so far.)"}]})
    if not native or native[-1]["role"] != "user":
        native.append({"role": "user", "content": [{"type": "text", "text": "Continue."}]})
    return system, native


def build_request(model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]],
                  max_tokens: int, effort: str = "", ttl: Optional[str] = None,
                  tool_choice: Any = None) -> Dict[str, Any]:
    """The Messages API request for one camel call, with the cache breakpoints described in the module docstring."""
    cc = _cache_control(ttl)
    system, native = messages_to_native(messages)
    native_tools = tools_to_native(tools)
    params: Dict[str, Any] = {"model": model, "max_tokens": int(max_tokens), "messages": native}
    if native_tools:
        native_tools[-1] = {**native_tools[-1], "cache_control": cc}
        params["tools"] = native_tools
        params["cache_control"] = cc                       # automatic: follows the growing memory
        if isinstance(tool_choice, str) and tool_choice in ("auto", "none"):
            params["tool_choice"] = {"type": tool_choice}
    elif len(native) >= 2:
        last = native[-2]["content"][-1]                    # the end of the memory, before the one-off question
        native[-2]["content"][-1] = {**last, "cache_control": cc}
    if system:
        system[-1] = {**system[-1], "cache_control": cc}
        params["system"] = system
    if effort in ("low", "medium", "high", "xhigh", "max") and effort_supported(model):
        params["output_config"] = {"effort": effort}
    return params


def to_chat_completion(msg: Any, tag: str = "agents") -> ChatCompletion:
    """A Messages API response -> the OpenAI ChatCompletion camel expects; the usage is added to the meter."""
    if getattr(msg, "stop_reason", None) == "refusal":
        raise RuntimeError("Claude declined the request (refusal: "
                           f"{getattr(getattr(msg, 'stop_details', None), 'category', None)})")
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    calls = [ChatCompletionMessageToolCall(
        id=b.id, type="function",
        function=Function(name=b.name, arguments=json.dumps(getattr(b, "input", None) or {}, ensure_ascii=False)))
        for b in msg.content if getattr(b, "type", "") == "tool_use"]
    u = msg.usage
    read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    uncached = int(getattr(u, "input_tokens", 0) or 0)
    output = int(getattr(u, "output_tokens", 0) or 0)
    _add_usage(tag, uncached, read, write, output)
    usage = CompletionUsage.model_construct(
        prompt_tokens=uncached + read + write, completion_tokens=output, total_tokens=uncached + read + write + output,
        prompt_tokens_details=PromptTokensDetails(cached_tokens=read),
        cache_read_input_tokens=read, cache_creation_input_tokens=write, uncached_input_tokens=uncached)
    message = ChatCompletionMessage.model_construct(role="assistant", content=text, tool_calls=calls or None)
    choice = Choice.model_construct(index=0, message=message, finish_reason=_FINISH.get(msg.stop_reason, "stop"),
                                    logprobs=None)
    return ChatCompletion.model_construct(id=msg.id, choices=[choice], created=int(time.time()), model=msg.model,
                                          object="chat.completion", usage=usage)


# ---------------------------------------------------------------------------------------------------
# The camel backend
# ---------------------------------------------------------------------------------------------------

class ClaudeNativeModel(OpenAICompatibleModel):
    """camel model backend for Claude on the native Messages API, with prompt caching (see the module docstring).
    `client` / `async_client` take fake anthropic clients in tests."""

    def __init__(self, model_type: str, model_config_dict: Optional[Dict[str, Any]] = None,
                 api_key: Optional[str] = None, url: Optional[str] = None, timeout: Optional[float] = None,
                 max_retries: int = 3, client: Any = None, async_client: Any = None, **kwargs: Any) -> None:
        super().__init__(model_type=model_type, model_config_dict=model_config_dict, api_key=api_key or "unused",
                         url=url or "https://api.anthropic.com/v1/", timeout=timeout, max_retries=max_retries,
                         **kwargs)
        self._native = client
        self._async_native = async_client
        self.usage_tag = "agents"
        self.effort = agent_effort()

    def _sdk_kwargs(self) -> Dict[str, Any]:
        return {"api_key": self._api_key, "timeout": self._timeout, "max_retries": self._max_retries}

    @property
    def native_client(self) -> Any:
        if self._native is None:
            import anthropic
            self._native = anthropic.Anthropic(**self._sdk_kwargs())
        return self._native

    @property
    def async_native_client(self) -> Any:
        if self._async_native is None:
            import anthropic
            self._async_native = anthropic.AsyncAnthropic(**self._sdk_kwargs())
        return self._async_native

    def _params(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        cfg = self.model_config_dict or {}
        return build_request(str(self.model_type), messages, tools,
                             max_tokens=int(cfg.get("max_tokens") or cfg.get("max_completion_tokens") or 4096),
                             effort=self.effort, tool_choice=cfg.get("tool_choice"))

    def _run(self, messages, response_format=None, tools=None):
        if response_format is not None or (self.model_config_dict or {}).get("response_format"):
            return super()._run(messages, response_format, tools)    # structured output: not used by OASIS
        return to_chat_completion(self.native_client.messages.create(**self._params(messages, tools)), self.usage_tag)

    async def _arun(self, messages, response_format=None, tools=None):
        if response_format is not None or (self.model_config_dict or {}).get("response_format"):
            return await super()._arun(messages, response_format, tools)
        msg = await self.async_native_client.messages.create(**self._params(messages, tools))
        return to_chat_completion(msg, self.usage_tag)

    @property
    def stream(self) -> bool:
        return False


def native_model_for(model: str, base_url: Optional[str], api_key: Optional[str],
                     model_config_dict: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Optional[ClaudeNativeModel]:
    """A ClaudeNativeModel when this slot is Claude on api.anthropic.com with a key (and MM_CLAUDE_NATIVE is not off),
    else None so the caller keeps its OpenAI-compatible model (login gateways, other providers)."""
    if not (api_key and str(model or "").startswith("claude") and is_anthropic_api(base_url)
            and native_claude_available()):
        return None
    return ClaudeNativeModel(model_type=model, model_config_dict=model_config_dict or {"max_tokens": 4096},
                             api_key=api_key, url=base_url, **kwargs)

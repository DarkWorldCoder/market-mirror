#!/usr/bin/env python3
"""
local_gateway.py - OpenAI-compatible local model gateway for MarketMirror.

An OpenAI-compatible server (POST /v1/chat/completions, GET /v1/models, GET /health) that fulfils every
request by the eligible-user Sign in with ChatGPT Responses API flow or a local CLI:

    claude  ->  claude -p <prompt> --output-format json --no-session-persistence --tools '' [--model M]
    codex   ->  codex exec --json -o <file> <prompt>   (ChatGPT login)

Point the engine at it and nothing else changes (OASIS agents, personas, feed test, survey, pitch all use
LLM_BASE_URL):

    LLM_PROVIDER=openai
    LLM_BASE_URL=http://127.0.0.1:5055/v1
    LLM_API_KEY=gateway
    LLM_GATEWAY=claude        # or codex

    python backend/gateway/local_gateway.py --backend claude --workers 6 --port 5055

CLI fallbacks start a process for each call. Identical low-temperature prompts
are cached in SQLite. Sign in with ChatGPT requires eligible account consent.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from . import siwc_auth
except ImportError:
    import siwc_auth

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = os.path.join(os.path.dirname(HERE), "uploads", "gateway_cache.sqlite")
STATS = {"requests": 0, "upstream_calls": 0, "cache_hits": 0, "failures": 0, "seconds": 0.0,
         "provider_input_tokens": 0, "provider_output_tokens": 0, "cost_usd": None, "cost_basis": None, "started": time.time()}
STATS_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# prompt handling
# --------------------------------------------------------------------------

def flatten_messages(messages: List[Dict[str, Any]]) -> Tuple[str, str]:
    """OpenAI messages -> (system, transcript). Multi-part content is joined; images are dropped."""
    system, turns = [], []
    for m in messages or []:
        role = str(m.get("role") or "user")
        content = m.get("content")
        if isinstance(content, list):
            content = "\n".join(str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type", "text") == "text")
        content = str(content or "")
        if role == "system":
            system.append(content)
        elif role == "assistant":
            calls = m.get("tool_calls") or []
            if calls:                                          # an earlier emulated tool call, shown as what was done
                done = "; ".join(f"called {((c.get('function') or {}).get('name'))}({(c.get('function') or {}).get('arguments') or ''})"
                                 for c in calls if isinstance(c, dict))
                content = (content + "\n" if content else "") + f"(I {done})"
            turns.append(f"[Assistant]\n{content}")
        elif role == "tool":
            turns.append(f"[Tool result{(' for ' + str(m.get('name'))) if m.get('name') else ''}]\n{content}")
        else:
            turns.append(f"[User]\n{content}")
    if len(turns) == 1 and turns[0].startswith("[User]\n"):
        return "\n\n".join(system), turns[0][len("[User]\n"):]      # the common case: one user message, sent as is
    transcript = "\n\n".join(turns)
    if len(turns) > 1:
        transcript += "\n\n[Assistant]\n"
    return "\n\n".join(system), transcript


GUARD = ("You are answering through an API relay. Reply with the answer only: no preamble, no markdown fences unless "
         "asked, no questions back, no tool use. If the request asks for JSON, output only the JSON.")


# --------------------------------------------------------------------------
# tool-call emulation: the CLIs return text only, so the tools are described in the prompt and the reply
# (one JSON object) is turned back into OpenAI tool_calls. OASIS agents choose their action this way.
# --------------------------------------------------------------------------

def _tool_specs(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for t in tools or []:
        f = t.get("function") if isinstance(t, dict) and t.get("type", "function") == "function" else None
        if isinstance(f, dict) and f.get("name"):
            params = f.get("parameters") or {}
            props = params.get("properties") or {}
            out.append({"name": f["name"], "description": str(f.get("description") or "")[:300],
                        "arguments": {k: {"type": (v or {}).get("type", "string"), "description": str((v or {}).get("description") or "")[:120]}
                                      for k, v in props.items()},
                        "required": list(params.get("required") or [])})
    return out


def tool_instructions(tools: List[Dict[str, Any]], tool_choice: Any = "auto") -> str:
    specs = _tool_specs(tools)
    if not specs:
        return ""
    forced = None
    if isinstance(tool_choice, dict):
        forced = ((tool_choice.get("function") or {}).get("name"))
    rule = ("You must call exactly this tool: " + forced) if forced else \
        ("You must call one of the tools." if tool_choice == "required" else
         "Call the one tool that fits what you decide to do; if no tool fits, answer in plain words instead.")
    return ("\n\n[Tools you can call]\n" + json.dumps(specs, ensure_ascii=False) + "\n\n" + rule +
            "\nTo call a tool, reply with ONLY this JSON and nothing else: "
            '{"tool_calls": [{"name": "<tool name>", "arguments": {<arguments>}}]}. '
            'To answer without a tool, reply with ONLY: {"content": "<your answer>"}.')


def _json_object(text: str) -> Optional[Dict[str, Any]]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        v = json.loads(t[start:end + 1])
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def parse_tool_reply(text: str, tools: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """-> (content, tool_calls in OpenAI format). Unknown tool names are dropped; nothing parseable means plain content."""
    names = {s["name"] for s in _tool_specs(tools)}
    data = _json_object(text)
    if data is None:
        return text, []
    raw = data.get("tool_calls")
    if raw is None and data.get("name"):
        raw = [data]
    calls = []
    for i, c in enumerate(raw or []):
        if not isinstance(c, dict):
            continue
        fn = c.get("function") if isinstance(c.get("function"), dict) else c
        name = fn.get("name")
        if name not in names:
            continue
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        calls.append({"id": f"call_{int(time.time() * 1000)}_{i}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False)}})
    if calls:
        return None, calls
    content = data.get("content")
    return (str(content) if content is not None else text), []


def cache_key(backend: str, model: str, system: str, prompt: str, temperature: float) -> str:
    h = hashlib.sha256()
    h.update(f"{backend}|{model}|{round(temperature, 2)}|".encode())
    h.update(system.encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(prompt.encode("utf-8", "replace"))
    return h.hexdigest()


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------

class Backend:
    name = "base"

    def __init__(self, model: Optional[str] = None, timeout: float = 180, binary: Optional[str] = None):
        self.model = model
        self.timeout = timeout
        self.binary = binary or self.name
        self.usage = threading.local()
        self.request = threading.local()

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def complete(self, system: str, prompt: str) -> str:
        raise NotImplementedError


class GatewayError(RuntimeError):
    def __init__(self, message: str, status: int = 502, kind: str = "backend_error", retry_at: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.retry_at = retry_at


LIMIT_WORDS = ("rate limit", "rate_limit", "usage limit", "limit reached", "session limit", "hit your limit",
               "weekly limit", "out of credits", "quota exceeded", "too many requests")
DEFAULT_PAUSE_S = 15 * 60          # when the message names no reset time
RESET_GRACE_S = 60


def parse_reset(text: str, now: Optional[float] = None) -> Optional[float]:
    """When a usage limit lifts, as an epoch, from the wording the CLIs use:
    "resets 12:45pm (Asia/Kathmandu)", "try again at 3:05 PM", "try again in 2 hours 13 minutes",
    "usage limit reached|1760000000", "Retry after 120 seconds". None when no time is given."""
    import re
    from datetime import datetime, timedelta
    now = time.time() if now is None else now
    low = text.lower()
    m = re.search(r"limit reached\|(\d{9,11})", low)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:try again|retry|resets?)\s+(?:in|after)\s+((?:\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b[\s,and]*)+)", low)
    if m:
        secs = 0
        for n, unit in re.findall(r"(\d+)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", m.group(1)):
            secs += int(n) * (86400 if unit.startswith("d") else 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
        return now + secs if secs else None
    m = re.search(r"(?:resets?|try again at|available at|reset at)\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(([A-Za-z_]+/[A-Za-z_]+)\))?", text, re.I)
    if m:
        hour, minute, ampm, tzname = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), m.group(4)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None
        tz = None
        if tzname:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tzname)
            except Exception:  # noqa: BLE001 - unknown zone: local time
                tz = None
        base = datetime.fromtimestamp(now, tz) if tz else datetime.fromtimestamp(now)
        at = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at.timestamp() <= now:
            at += timedelta(days=1)
        return at.timestamp()
    return None


def cli_failure(name: str, detail: str, status: Optional[int] = None) -> GatewayError:
    """Classify actionable CLI failures without echoing its captured payload."""
    text = detail.lower()
    if status in (401, 403) or any(s in text for s in ("not logged in", "authentication", "invalid api key", "expired token", "please run /login")):
        return GatewayError(f"{name} authorization failed or expired. Log in to that CLI and retry.", 401, "authentication_error")
    if status == 429 or any(s in text for s in LIMIT_WORDS):
        return GatewayError(f"{name} usage is limited. Wait for the account limit to reset before retrying.", 429, "rate_limit",
                            retry_at=parse_reset(detail))
    return GatewayError(f"{name} CLI request failed. Check its local login and model availability.")


class ClaudeBackend(Backend):
    name = "claude"

    def complete(self, system: str, prompt: str) -> str:
        # --bare disables OAuth/keychain reads in current Claude Code releases.
        # Keep the user's normal login while disabling tools, MCP, skills and hooks.
        output_limit = getattr(self.request, "max_tokens", None) or int(os.environ.get("LLM_GATEWAY_MAX_OUTPUT_TOKENS") or 8192)
        settings = {"disableAllHooks": True, "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(output_limit)}}
        if os.environ.get("LLM_GATEWAY_EFFORT"):
            settings["env"]["CLAUDE_CODE_EFFORT_LEVEL"] = os.environ["LLM_GATEWAY_EFFORT"]
        cmd = [self.binary, "-p", prompt, "--output-format", "json", "--no-session-persistence",
               "--tools", "", "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--settings", json.dumps(settings),
               "--system-prompt", (GUARD + "\n\n" + system).strip()]
        if self.model:
            cmd += ["--model", self.model]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            raise cli_failure("claude", p.stderr + p.stdout)
        try:
            record = json.loads(p.stdout)
            reported = record.get("usage") or {}
            input_tokens = sum(int(reported.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            output_tokens = int(reported.get("output_tokens") or 0)
            self.usage.value = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                                "uncached_input_tokens": int(reported.get("input_tokens") or 0),
                                "cache_read_input_tokens": int(reported.get("cache_read_input_tokens") or 0),
                                "cache_creation_input_tokens": int(reported.get("cache_creation_input_tokens") or 0),
                                "total_tokens": input_tokens + output_tokens,
                                "cost_usd": record.get("total_cost_usd"), "cost_basis": "cli_reported_list_cost"} if reported else None
        except (ValueError, AttributeError, TypeError):
            self.usage.value = None
        return parse_claude_output(p.stdout)


def parse_claude_output(out: str) -> str:
    out = out.strip()
    try:
        data = json.loads(out)
    except ValueError:
        # stream or stray lines: take the last JSON object that has a result
        data = None
        for line in reversed(out.splitlines()):
            try:
                cand = json.loads(line)
            except ValueError:
                continue
            if isinstance(cand, dict) and ("result" in cand or "content" in cand):
                data = cand
                break
        if data is None:
            return out
    if isinstance(data, dict):
        if data.get("is_error") and data.get("result"):
            raise cli_failure("claude", str(data["result"]), data.get("api_error_status"))
        if isinstance(data.get("result"), str):
            return data["result"]
        if isinstance(data.get("content"), list):
            return "\n".join(str(c.get("text") or "") for c in data["content"] if isinstance(c, dict))
    return out


class CodexBackend(Backend):
    name = "codex"

    def complete(self, system: str, prompt: str) -> str:
        full = (GUARD + ("\n\n" + system if system else "") + "\n\n" + prompt).strip()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
            out_path = tmp.name
        try:
            cmd = [self.binary, "exec", "--json", "-o", out_path, "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only"]
            if self.model:
                cmd += ["-m", self.model]
            cmd.append(full)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
            if p.returncode != 0:
                raise cli_failure("codex", p.stderr + p.stdout)
            try:
                with open(out_path, encoding="utf-8") as f:
                    text = f.read().strip()
            except OSError:
                text = ""
            return text or parse_codex_events(p.stdout)
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass


def parse_codex_events(out: str) -> str:
    """JSONL events from `codex exec --json`: the last agent message wins."""
    last = ""
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        item = ev.get("item") if isinstance(ev.get("item"), dict) else ev
        if item.get("type") in ("agent_message", "message", "assistant_message") and item.get("text"):
            last = str(item["text"])
        elif isinstance(ev.get("msg"), dict) and ev["msg"].get("type") == "agent_message" and ev["msg"].get("message"):
            last = str(ev["msg"]["message"])
    return last or out.strip()


class SignInBackend(Backend):
    name = "siwc"

    def __init__(self, model: Optional[str] = None, timeout: float = 180, binary: Optional[str] = None):
        super().__init__(model=model, timeout=timeout, binary=binary)
        self.usage = threading.local()
        self.model = model or siwc_auth.status().get("model")

    def available(self) -> bool:
        s = siwc_auth.status()
        return bool(s["registered"] and s["eligible_scope"] and not s["needs_login"] and s["model"])

    def complete(self, system: str, prompt: str) -> str:
        try:
            token, authorized_model = siwc_auth.access_token()
        except siwc_auth.SignInError as e:
            raise GatewayError(str(e), 401, "authentication_error") from e
        model = self.model or authorized_model
        body = {"model": model, "instructions": (GUARD + "\n\n" + system).strip(),
                "input": [{"role": "user", "content": prompt}], "store": False, "stream": True}
        try:
            response = requests.post("https://api.openai.com/v1/responses", json=body,
                                     headers={"Authorization": "Bearer " + token}, stream=True, timeout=self.timeout)
        except requests.Timeout as e:
            raise GatewayError("Responses API timed out", 504, "timeout") from e
        except requests.RequestException as e:
            raise GatewayError("Responses API unavailable", 503, "upstream_unavailable") from e
        if not response.ok:
            code = response.status_code
            kind = "authentication_error" if code in (401, 403) else "rate_limit" if code == 429 else "upstream_error"
            raise GatewayError(f"Responses API returned HTTP {code}", code if code in (401, 403, 429) else 502, kind)
        response.encoding = "utf-8"
        chunks, completed = [], False
        self.usage.value = None
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    chunks.append(event.get("delta") or "")
                elif event_type == "response.completed":
                    completed = True
                    self.usage.value = (event.get("response") or {}).get("usage")
                elif event_type == "response.failed":
                    err = (event.get("response") or {}).get("error") or {}
                    code = err.get("code") or "response_failed"
                    status = 429 if "usage" in code or "rate" in code else 502
                    raise GatewayError(f"Responses API failed: {code}", status, "rate_limit" if status == 429 else "upstream_error")
                elif event_type == "response.incomplete":
                    raise GatewayError("Responses API response incomplete", 502, "incomplete")
        finally:
            response.close()
        if not completed:
            raise GatewayError("Responses API stream ended without response.completed", 502, "incomplete")
        return "".join(chunks)


BACKENDS = {"claude": ClaudeBackend, "codex": CodexBackend, "siwc": SignInBackend}


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

class Cache:
    def __init__(self, path: Optional[str]):
        self.path = path
        self.lock = threading.Lock()
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with sqlite3.connect(path) as c:
                c.execute("CREATE TABLE IF NOT EXISTS completions (key TEXT PRIMARY KEY, text TEXT, created REAL)")
            os.chmod(path, 0o600)

    def get(self, key: str) -> Optional[str]:
        if not self.path:
            return None
        with self.lock, sqlite3.connect(self.path) as c:
            row = c.execute("SELECT text FROM completions WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, text: str) -> None:
        if not self.path:
            return
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO completions VALUES (?,?,?)", (key, text, time.time()))


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------

class Gateway:
    def __init__(self, backend: Backend, workers: int = 6, cache: Optional[Cache] = None, auth_token: Optional[str] = None):
        self.backend = backend
        self.cache = cache or Cache(None)
        self.slots = threading.BoundedSemaphore(max(1, workers))
        self.workers = workers
        self.auth_token = auth_token
        self.paused_until = 0.0         # usage limit: answer 429 locally until then, no upstream calls

    def pause(self, retry_at: Optional[float]) -> float:
        if not retry_at or retry_at <= time.time():
            retry_at = time.time() + DEFAULT_PAUSE_S
        until = retry_at + RESET_GRACE_S
        with STATS_LOCK:
            if until > self.paused_until:
                self.paused_until = until
            STATS["limit_hits"] = STATS.get("limit_hits", 0) + 1
        return self.paused_until

    def pause_state(self) -> Dict[str, Any]:
        left = self.paused_until - time.time()
        return {"paused": left > 0, "paused_until": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.paused_until)) if left > 0 else None,
                "paused_until_epoch": self.paused_until if left > 0 else None, "resume_in_s": max(0, int(left)),
                "limit_hits": STATS.get("limit_hits", 0)}

    def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        system, prompt = flatten_messages(body.get("messages") or [])
        if not prompt.strip():
            raise ValueError("messages must contain a user message")
        tools = body.get("tools") or []
        if tools and body.get("tool_choice") != "none":
            prompt += tool_instructions(tools, body.get("tool_choice", "auto"))
        temperature = float(body.get("temperature") or 0)
        max_tokens = body.get("max_completion_tokens", body.get("max_tokens"))
        if max_tokens is not None and (isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 128000):
            raise ValueError("max_tokens must be an integer between 1 and 128000")
        self.backend.request.max_tokens = max_tokens
        # A local relay has one configured model. Reflect the actual selection,
        # rather than echoing an arbitrary request model the CLI never received.
        model = str(self.backend.model or self.backend.name)
        key = cache_key(self.backend.name, model, system, prompt, temperature)
        key = hashlib.sha256(f"{key}|{max_tokens}".encode()).hexdigest()
        cached = self.cache.get(key) if temperature <= 0.3 else None      # creative calls are not cached
        t0 = time.time()
        if cached is not None:
            text = cached
            if getattr(self.backend, "usage", None) is not None:
                self.backend.usage.value = None
            with STATS_LOCK:
                STATS["cache_hits"] += 1
        else:
            if time.time() < self.paused_until:
                raise GatewayError(f"{self.backend.name} usage is limited; paused until the reset.", 429, "rate_limit",
                                   retry_at=self.paused_until)
            with self.slots:
                try:
                    text = self.backend.complete(system, prompt)
                except GatewayError as e:
                    if e.status == 429:
                        e.retry_at = self.pause(e.retry_at)
                    raise
            with STATS_LOCK:
                STATS["upstream_calls"] += 1
            if temperature <= 0.3:
                self.cache.put(key, text)
        with STATS_LOCK:
            STATS["requests"] += 1
            STATS["seconds"] += time.time() - t0
        usage = getattr(getattr(self.backend, "usage", None), "value", None)
        if cached is not None:
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                     "uncached_input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                     "cost_usd": 0, "cost_basis": "no_upstream_call", "source": "local_cache"}
        if usage and cached is None:
            with STATS_LOCK:
                STATS["provider_input_tokens"] += int(usage.get("input_tokens") or 0)
                STATS["provider_output_tokens"] += int(usage.get("output_tokens") or 0)
                if isinstance(usage.get("cost_usd"), (int, float)):
                    STATS["cost_usd"] = (STATS["cost_usd"] or 0) + usage["cost_usd"]
                    STATS["cost_basis"] = usage.get("cost_basis")
        if tools and body.get("tool_choice") != "none":
            content, calls = parse_tool_reply(text, tools)
            with STATS_LOCK:
                STATS["tool_calls"] = STATS.get("tool_calls", 0) + len(calls)
            return openai_response(content, model, prompt, system, usage, tool_calls=calls)
        return openai_response(text, model, prompt, system, usage)


def openai_response(text: Optional[str], model: str, prompt: str = "", system: str = "", usage: Optional[Dict[str, Any]] = None,
                    tool_calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    text_len = len(text or "")
    approx_in = (len(prompt) + len(system)) // 4
    u = {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0),
         "total_tokens": usage.get("total_tokens", 0)} if usage else \
        {"prompt_tokens": approx_in, "completion_tokens": text_len // 4, "total_tokens": approx_in + text_len // 4}
    return {"id": f"chatcmpl-gw{int(time.time() * 1000)}", "object": "chat.completion", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text, **({"tool_calls": tool_calls} if tool_calls else {})},
                         "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": u, "usage_source": usage.get("source", "provider") if usage else "estimated",
            "usage_breakdown": {k: usage.get(k) for k in ("uncached_input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")} if usage else None,
            "cost_usd": usage.get("cost_usd") if usage else None,
            "cost_basis": usage.get("cost_basis") if usage else None}


def make_handler(gw: Gateway):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet by default
            if os.environ.get("GATEWAY_VERBOSE"):
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code: int, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/") in ("/health", ""):
                with STATS_LOCK:
                    stats = dict(STATS)
                self._send(200, {"status": "ok", "backend": gw.backend.name, "model": gw.backend.model,
                                 "available": gw.backend.available(), "auth_required": bool(gw.auth_token),
                                 "workers": gw.workers, **stats, **gw.pause_state()})
            elif self.path.startswith("/v1/models"):
                self._send(200, {"object": "list", "data": [{"id": gw.backend.model or gw.backend.name, "object": "model",
                                                             "owned_by": gw.backend.name}]})
            else:
                self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):
            if not self.path.startswith("/v1/chat/completions"):
                self._send(404, {"error": {"message": "not found"}})
                return
            if gw.auth_token and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + gw.auth_token):
                self._send(401, {"error": {"message": "invalid local gateway token", "type": "authentication_error"}})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                resp = gw.complete(body)
                if body.get("stream"):
                    # one chunk, then [DONE]: enough for clients that insist on streaming
                    msg = resp["choices"][0]["message"]
                    delta = {"role": "assistant", "content": msg.get("content")}
                    if msg.get("tool_calls"):
                        delta["tool_calls"] = [{**c, "index": i} for i, c in enumerate(msg["tool_calls"])]
                    chunk = {"id": resp["id"], "object": "chat.completion.chunk", "created": resp["created"], "model": resp["model"],
                             "choices": [{"index": 0, "delta": delta, "finish_reason": resp["choices"][0]["finish_reason"]}]}
                    data = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._send(200, resp)
            except ValueError as e:
                self._send(400, {"error": {"message": str(e), "type": "invalid_request_error"}})
            except subprocess.TimeoutExpired:
                with STATS_LOCK:
                    STATS["failures"] += 1
                self._send(504, {"error": {"message": f"{gw.backend.name} timed out after {gw.backend.timeout}s", "type": "timeout"}})
            except GatewayError as e:
                with STATS_LOCK:
                    STATS["failures"] += 1
                err: Dict[str, Any] = {"message": str(e), "type": e.kind}
                headers = {}
                if e.status == 429 and e.retry_at:
                    err["resets_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(e.retry_at))
                    headers["Retry-After"] = str(max(1, int(e.retry_at - time.time())))
                self._send(e.status, {"error": err}, headers)
            except Exception as e:  # noqa: BLE001
                with STATS_LOCK:
                    STATS["failures"] += 1
                self._send(502, {"error": {"message": str(e)[:500], "type": "backend_error"}})

    return Handler


def serve(backend: Backend, host: str, port: int, workers: int, cache_path: Optional[str], auth_token: str) -> None:
    gw = Gateway(backend, workers, Cache(cache_path), auth_token)
    srv = ThreadingHTTPServer((host, port), make_handler(gw))
    srv.daemon_threads = True
    sys.stderr.write(json.dumps({"gateway": backend.name, "model": backend.model, "url": f"http://{host}:{port}/v1",
                                 "workers": workers, "available": backend.available(), "cache": cache_path}) + "\n")
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="OpenAI-compatible gateway over Sign in with ChatGPT or local CLI fallbacks.")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default=os.environ.get("LLM_GATEWAY", "claude"))
    ap.add_argument("--model", default=os.environ.get("LLM_GATEWAY_MODEL") or None, help="model passed to the CLI (optional)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LLM_GATEWAY_PORT") or 5055))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("LLM_GATEWAY_WORKERS") or 2))
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("LLM_GATEWAY_TIMEOUT") or 180))
    ap.add_argument("--cache", default=os.environ.get("LLM_GATEWAY_CACHE") or DEFAULT_CACHE, help="SQLite cache path ('' to disable)")
    ap.add_argument("--binary", help="path to the CLI binary (default: on PATH)")
    ap.add_argument("--auth-token-file", help="0600 file containing the local gateway bearer token")
    ap.add_argument("--check", action="store_true", help="print availability and exit")
    a = ap.parse_args(argv)
    backend = BACKENDS[a.backend](model=a.model, timeout=a.timeout, binary=a.binary)
    if a.check:
        print(json.dumps({"backend": a.backend, "available": backend.available(),
                          "binary": shutil.which(backend.binary) if a.backend != "siwc" else None}))
        return 0 if backend.available() else 1
    if not backend.available():
        sys.stderr.write("error: provider unavailable; run Sign in with ChatGPT setup or log in to the selected CLI.\n")
        return 1
    if a.host not in ("127.0.0.1", "localhost"):
        sys.stderr.write("error: gateway only serves loopback\n")
        return 1
    if not a.auth_token_file:
        sys.stderr.write("error: --auth-token-file is required\n")
        return 1
    with open(a.auth_token_file, encoding="utf-8") as f:
        auth_token = f.read().strip()
    if len(auth_token) < 24:
        sys.stderr.write("error: gateway token must be at least 24 characters\n")
        return 1
    serve(backend, a.host, a.port, a.workers, a.cache or None, auth_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())

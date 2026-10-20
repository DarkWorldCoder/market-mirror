#!/usr/bin/env python3
"""
local_gateway.py - OpenAI-compatible local model gateway for MarketMirror.

An OpenAI-compatible server (POST /v1/chat/completions, GET /v1/models, GET /health) that fulfils every
request by the eligible-user Sign in with ChatGPT Responses API flow or a local CLI:

    claude       ->  claude -p --output-format json --no-session-persistence --tools '' [--model M]   (prompt on stdin)
    codex        ->  codex exec --json -o <file> --ignore-user-config -c mcp_servers={} ... -   (ChatGPT login, stdin)
    gemini       ->  gemini --output-format json --approval-mode plan -e none -p ...   (Google login, stdin)
    antigravity  ->  agy --input-format stream-json --output-format stream-json --sandbox --model M -p=   (stdin)

Every CLI call runs in a fresh empty temporary directory with tools, MCP servers and user/project context
disabled as far as the CLI allows, so ad copy inside a prompt cannot make the CLI act on this repository.

Point the engine at it and nothing else changes (OASIS agents, personas, feed test, survey, pitch all use
LLM_BASE_URL):

    LLM_PROVIDER=openai
    LLM_BASE_URL=http://127.0.0.1:5055/v1
    LLM_API_KEY=<the token in --auth-token-file>
    LLM_GATEWAY=claude        # or codex, gemini, antigravity, multi

    python backend/gateway/local_gateway.py --backend claude --workers 6 --port 5055 --auth-token-file F

Several gateways can run side by side (one per provider), each on its own port with its own token file; the
default cache file is per port (gateway_cache.sqlite on 5055, gateway_cache_<port>.sqlite elsewhere, under
MIROFISH_UPLOAD_DIR or backend/uploads). Responses name the backend that answered (the "provider" field and
the X-MarketMirror-Backend header). Identical low-temperature prompts are cached in SQLite. Sign in with
ChatGPT requires eligible account consent.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import hmac
import json
import os
import queue
import re
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
DEFAULT_PORT = 5055


def upload_dir() -> str:
    """MIROFISH_UPLOAD_DIR (one per backend instance) or backend/uploads."""
    return os.path.abspath(os.environ.get("MIROFISH_UPLOAD_DIR") or os.path.join(os.path.dirname(HERE), "uploads"))


def default_cache_path(port: int) -> str:
    """One cache file per gateway port, so gateways running side by side never share a cache file."""
    name = "gateway_cache.sqlite" if int(port) == DEFAULT_PORT else f"gateway_cache_{int(port)}.sqlite"
    return os.path.join(upload_dir(), name)


DEFAULT_CACHE = default_cache_path(DEFAULT_PORT)
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
    known_paths: Tuple[str, ...] = ()        # where the CLI lives when it is not on PATH

    def __init__(self, model: Optional[str] = None, timeout: float = 180, binary: Optional[str] = None):
        self.model = model
        self.timeout = timeout
        self.binary = binary or resolve_binary(self.name if self.name != "antigravity" else "agy", self.known_paths)
        self.usage = threading.local()
        self.request = threading.local()

    def available(self) -> bool:
        return binary_path(self.binary) is not None

    def complete(self, system: str, prompt: str) -> str:
        raise NotImplementedError

    def run_cli(self, cmd: List[str], stdin_text: Optional[str], cwd: Optional[str] = None,
                timeout: Optional[float] = None) -> "subprocess.CompletedProcess[str]":
        """Run the CLI with the prompt on stdin. A missing binary or a timeout becomes a GatewayError so the
        HTTP layer and the multi pool can classify it (503 / 504) instead of crashing."""
        try:
            return subprocess.run(cmd, input=stdin_text if stdin_text is not None else "", capture_output=True, text=True,
                                  timeout=timeout or self.timeout, cwd=cwd)
        except FileNotFoundError as e:
            raise GatewayError(f"{self.name} CLI not found ({os.path.basename(cmd[0])}); install it or pass --binary.",
                               503, "upstream_unavailable") from e
        except subprocess.TimeoutExpired as e:
            raise GatewayError(f"{self.name} timed out after {int(timeout or self.timeout)}s", 504, "timeout") from e


def binary_path(binary: str) -> Optional[str]:
    """Absolute path of an executable given by name (on PATH) or by path, else None."""
    if not binary:
        return None
    if os.sep in binary:
        return binary if os.path.isfile(binary) and os.access(binary, os.X_OK) else None
    return shutil.which(binary)


def resolve_binary(name: str, known: Tuple[str, ...] = ()) -> str:
    """The CLI on PATH, else the first executable known install location (globs allowed), else the bare name."""
    found = shutil.which(name)
    if found:
        return found
    for pattern in known:
        for cand in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return name


CLAUDE_ALIASES = ("haiku", "sonnet", "opus")
GEMINI_ALIASES = ("flash", "pro")
ARG_SAFE_CHARS = 100_000                 # Linux caps a single argument at 128 KiB (MAX_ARG_STRLEN)
# never fall back to the CLI's own default (often the largest model). Antigravity defaults to a Gemini model: its
# Claude models would duplicate a Claude Code run.
DEFAULT_MODELS = {"claude": "sonnet", "gemini": "gemini-2.5-flash", "antigravity": "gemini-4-argon-medium"}
CLAUDE_MIN_OUTPUT_TOKENS = int(os.environ.get("LLM_GATEWAY_MIN_OUTPUT_TOKENS") or 2048)
_EFFORT_SUFFIX = re.compile(r"-(low|medium|high|xhigh|max)$")


def request_model(backend_name: str, model: Any) -> Optional[str]:
    """The request's model when this backend can run it ("haiku", "sonnet", "claude-sonnet-5-5", "gemini-2.5-flash",
    "gemini-4-argon-medium" on antigravity), else None."""
    m = str(model or "").strip()
    low = m.lower()
    effort_named = bool(_EFFORT_SUFFIX.search(low))      # Antigravity's ids end in an effort level
    if backend_name == "claude" and not effort_named and (low in CLAUDE_ALIASES or (low.startswith("claude-") and len(m) > 7)):
        return m
    # "codex" / "chatgpt" alone are generic names (LLM_MODEL_NAME written by mm.sh): the gateway's own model
    if backend_name in ("codex", "chatgpt") and low.startswith(("gpt-", "o1", "o3", "o4", "codex-", "chatgpt-")) \
            and not low.startswith("gpt-oss-"):
        return m
    if backend_name == "gemini" and not effort_named:
        if low.startswith("models/gemini-"):
            return m.split("/", 1)[1]
        if low in GEMINI_ALIASES or (low.startswith("gemini-") and len(m) > 7):
            return m
    if backend_name == "antigravity":
        if low.startswith("gpt-oss-") or (effort_named and low.startswith(("gemini-", "claude-"))):
            return m
    if backend_name == "multi":
        for sub in ("claude", "codex", "chatgpt", "gemini", "antigravity"):
            resolved = request_model(sub, m)
            if resolved:
                return resolved
    return None


class GatewayError(RuntimeError):
    def __init__(self, message: str, status: int = 502, kind: str = "backend_error", retry_at: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.retry_at = retry_at


LIMIT_WORDS = ("rate limit", "rate_limit", "usage limit", "limit reached", "session limit", "hit your limit",
               "weekly limit", "out of credits", "quota exceeded", "too many requests", "resource_exhausted",
               "resource exhausted", "quota")
AUTH_WORDS = ("not logged in", "authentication", "invalid api key", "expired token", "please run /login", "login required",
              "please log in", "please login", "auth method", "unauthenticated", "not authenticated", "sign in again",
              "invalid_grant", "permission_denied")
DEFAULT_PAUSE_S = 15 * 60          # when the message names no reset time
RESET_GRACE_S = 60
UNHEALTHY_S = float(os.environ.get("LLM_GATEWAY_UNHEALTHY_S") or 120)   # multi pool: skip a failing backend this long


def parse_reset(text: str, now: Optional[float] = None) -> Optional[float]:
    """When a usage limit lifts, as an epoch, from the wording the CLIs use:
    "resets 12:45pm (Asia/Kathmandu)", "try again at 3:05 PM", "try again in 2 hours 13 minutes",
    "usage limit reached|1760000000", "Retry after 120 seconds", Gemini's "Please retry in 25.3s" and
    "retryDelay": "25s". None when no time is given."""
    from datetime import datetime, timedelta
    now = time.time() if now is None else now
    low = text.lower()
    m = re.search(r"limit reached\|(\d{9,11})", low)
    if m:
        return float(m.group(1))
    m = re.search(r'retrydelay"?\s*[:=]\s*"?(\d+(?:\.\d+)?)s', low)
    if m:
        return now + float(m.group(1))
    m = re.search(r"(?:try again|retry|resets?|wait)\s+(?:in|after|for)?\s*(\d+\.\d+)\s*s(?:ec(?:ond)?s?)?\b", low)
    if m:
        return now + float(m.group(1))
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
    """Classify actionable CLI failures without echoing its captured payload to the client. With GATEWAY_VERBOSE set,
    the first 400 characters of the CLI's own message go to the gateway's log (stderr) for the operator."""
    if os.environ.get("GATEWAY_VERBOSE"):
        sys.stderr.write(f"[{name} failure] {' '.join(detail.split())[:400]}\n")
        sys.stderr.flush()
    text = detail.lower()
    if status in (401, 403) or any(s in text for s in AUTH_WORDS):
        return GatewayError(f"{name} authorization failed or expired. Log in to that CLI and retry.", 401, "authentication_error")
    if status == 429 or any(s in text for s in LIMIT_WORDS) or re.search(r"(?<![\d.])429(?![\d.])", text):
        return GatewayError(f"{name} usage is limited. Wait for the account limit to reset before retrying.", 429, "rate_limit",
                            retry_at=parse_reset(detail))
    return GatewayError(f"{name} CLI request failed. Check its local login and model availability.")


def _full_prompt(system: str, prompt: str) -> str:
    return (GUARD + ("\n\n" + system if system else "") + "\n\n" + prompt).strip()


class ClaudeBackend(Backend):
    name = "claude"

    def complete(self, system: str, prompt: str) -> str:
        # --bare disables OAuth/keychain reads in current Claude Code releases.
        # Keep the user's normal login while disabling tools, MCP, skills and hooks.
        output_limit = getattr(self.request, "max_tokens", None) or int(os.environ.get("LLM_GATEWAY_MAX_OUTPUT_TOKENS") or 8192)
        # the CLI counts thinking against this cap: a small max_tokens (200) ends the turn mid-thought with no answer
        output_limit = max(int(output_limit), CLAUDE_MIN_OUTPUT_TOKENS)
        settings = {"disableAllHooks": True, "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(output_limit)}}
        if os.environ.get("LLM_GATEWAY_EFFORT"):
            settings["env"]["CLAUDE_CODE_EFFORT_LEVEL"] = os.environ["LLM_GATEWAY_EFFORT"]
        # The prompt goes over stdin: a 1,000-person analyst brief is larger than the OS allows for one argument.
        sys_text = (GUARD + "\n\n" + system).strip()
        if len(sys_text) > ARG_SAFE_CHARS:
            prompt, sys_text = sys_text + "\n\n" + prompt, GUARD
        cmd = [self.binary, "-p", "--output-format", "json", "--no-session-persistence",
               "--tools", "", "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--setting-sources", "",          # no user/project settings, memory files or plugins in persona calls
               "--settings", json.dumps(settings),
               "--system-prompt", sys_text]
        model = getattr(self.request, "model", None) or self.model
        if model:
            cmd += ["--model", model]
        with tempfile.TemporaryDirectory(prefix="mm-claude-") as cwd:      # no project CLAUDE.md, no repo to act on
            p = self.run_cli(cmd, prompt, cwd=cwd)
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


# Codex features that add tools, connectors or context to every turn. Only the ones this codex version knows are
# disabled (an unknown name is an error), see CodexBackend._probe.
CODEX_DISABLE = ("apps", "plugins", "remote_plugin", "browser_use", "browser_use_external", "computer_use", "memories",
                 "image_generation", "multi_agent", "shell_tool", "unified_exec", "hooks", "skill_search", "tool_suggest",
                 "goals", "view_image", "in_app_browser", "sleep_tool", "skill_mcp_dependency_install", "shell_snapshot",
                 "workspace_dependencies", "web_search_request", "web_search_cached")
CODEX_FLAGS = ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check")


class CodexBackend(Backend):
    name = "codex"
    # The ChatGPT desktop app ships codex outside PATH.
    known_paths = ("/usr/lib/chatgpt/resources/codex", "~/.codex/plugins/.plugin-appserver/codex",
                   "/Applications/ChatGPT.app/Contents/Resources/codex")

    def __init__(self, model: Optional[str] = None, timeout: float = 180, binary: Optional[str] = None):
        super().__init__(model=model, timeout=timeout, binary=binary)
        self._probe_lock = threading.Lock()
        self._probed: Optional[Tuple[frozenset, frozenset]] = None

    def _probe(self) -> Tuple[frozenset, frozenset]:
        """(exec flags, feature names) this codex build understands; probed once, best effort."""
        with self._probe_lock:
            if self._probed is not None:
                return self._probed
            flags, features = set(), set()
            try:
                h = subprocess.run([self.binary, "exec", "--help"], capture_output=True, text=True, timeout=20)
                flags = {f for f in CODEX_FLAGS if f in (h.stdout + h.stderr)}
                f = subprocess.run([self.binary, "features", "list"], capture_output=True, text=True, timeout=20)
                features = {line.split()[0] for line in f.stdout.splitlines() if line.strip()}
            except (OSError, subprocess.SubprocessError):
                pass
            self._probed = (frozenset(flags), frozenset(features))
            return self._probed

    def command(self, cwd: str, out_path: str, instructions_path: str, model: Optional[str]) -> List[str]:
        flags, features = self._probe()
        cmd = [self.binary, "exec", "--json", "-o", out_path, "--sandbox", "read-only", "-C", cwd,
               *[f for f in CODEX_FLAGS if f in flags],
               # no MCP servers (they cost ~10k input tokens per call and log auth errors), no AGENTS.md, no web search,
               # and our guard + system prompt replace the coding-agent instructions
               "-c", "mcp_servers={}", "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
               "-c", "model_instructions_file=" + json.dumps(instructions_path)]
        for feat in CODEX_DISABLE:
            if feat in features:
                cmd += ["--disable", feat]
        if model:
            cmd += ["-m", model]
        cmd.append("-")                     # the prompt is read from stdin: no argument-size limit
        return cmd

    def complete(self, system: str, prompt: str) -> str:
        model = getattr(self.request, "model", None) or self.model
        with tempfile.TemporaryDirectory(prefix="mm-codex-") as cwd:
            out_path = os.path.join(cwd, ".last_message.txt")
            instructions = os.path.join(cwd, ".instructions.md")
            with open(instructions, "w", encoding="utf-8") as f:
                f.write((GUARD + ("\n\n" + system if system else "")).strip() + "\n")
            p = self.run_cli(self.command(cwd, out_path, instructions, model), prompt, cwd=cwd)
            if p.returncode != 0:
                raise cli_failure("codex", p.stderr + p.stdout)
            try:
                with open(out_path, encoding="utf-8") as f:
                    text = f.read().strip()
            except OSError:
                text = ""
        self.usage.value = parse_codex_usage(p.stdout)
        failure = codex_error(p.stdout)
        if not text and failure:
            raise cli_failure("codex", failure)
        return text or parse_codex_events(p.stdout)


def parse_codex_usage(out: str) -> Optional[Dict[str, Any]]:
    """Token usage from the `turn.completed` events of `codex exec --json`."""
    total_in = cached = out_tok = 0
    seen = False
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
            u = ev["usage"]
            seen = True
            total_in += int(u.get("input_tokens") or 0)
            cached += int(u.get("cached_input_tokens") or 0)
            out_tok += int(u.get("output_tokens") or 0)
    if not seen:
        return None
    return {"input_tokens": total_in, "output_tokens": out_tok, "uncached_input_tokens": max(0, total_in - cached),
            "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0, "total_tokens": total_in + out_tok,
            "cost_usd": None, "cost_basis": "cli_reported_tokens"}


def codex_error(out: str) -> str:
    """The message of a `turn.failed` / `error` event, if the turn failed."""
    msgs = []
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") in ("turn.failed", "error"):
            err = ev.get("error") if isinstance(ev.get("error"), dict) else ev
            msgs.append(str(err.get("message") or ""))
    return " ".join(m for m in msgs if m)


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


def parse_gemini_output(out: str) -> str:
    """Parse JSON or plain text output from the `gemini` CLI."""
    out = out.strip()
    if not out:
        return ""
    try:
        data = json.loads(out)
    except ValueError:
        data = None
        for line in reversed(out.splitlines()):
            try:
                cand = json.loads(line)
            except ValueError:
                continue
            if isinstance(cand, dict) and any(k in cand for k in ("response", "result", "text", "content", "error")):
                data = cand
                break
        if data is None:
            return out
    if isinstance(data, dict):
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            code = err.get("code") if isinstance(err, dict) else None
            raise cli_failure("gemini", str(msg or "gemini error"), code if isinstance(code, int) else None)
        for key in ("response", "result", "text", "output"):
            if isinstance(data.get(key), str):
                return data[key]
        if isinstance(data.get("content"), list):
            return "\n".join(str(c.get("text") or "") for c in data["content"] if isinstance(c, dict))
    return out


class GeminiBackend(Backend):
    name = "gemini"
    known_paths = ("~/.nvm/versions/node/*/bin/gemini", "~/.local/bin/gemini", "/usr/local/bin/gemini")

    def complete(self, system: str, prompt: str) -> str:
        model = getattr(self.request, "model", None) or self.model
        # Headless, read-only approval mode, no extensions or MCP servers, in an empty directory: ad copy in a prompt
        # cannot make it touch this repository. The whole prompt rides on stdin; -p only adds the closing line.
        cmd = [self.binary, "--output-format", "json", "--approval-mode", "plan", "-e", "none",
               "--allowed-mcp-server-names", "none"]
        if model:
            cmd += ["-m", model]
        cmd += ["-p", "Answer the request above."]
        with tempfile.TemporaryDirectory(prefix="mm-gemini-") as cwd:
            p = self.run_cli(cmd, _full_prompt(system, prompt), cwd=cwd)
        if p.returncode != 0:
            raise cli_failure("gemini", p.stderr + p.stdout)
        try:
            record = json.loads(p.stdout)
            stats = record.get("stats") or record.get("usage") or {}
            models_stats = stats.get("models") if isinstance(stats, dict) else None
            in_tok = 0
            out_tok = 0
            if isinstance(models_stats, dict):
                for mstat in models_stats.values():
                    tokens = (mstat or {}).get("tokens") or {}
                    in_tok += int(tokens.get("prompt") or tokens.get("input") or 0)
                    out_tok += int(tokens.get("candidates") or tokens.get("output") or 0)
            elif isinstance(stats, dict):
                in_tok = int(stats.get("input_tokens") or stats.get("prompt_tokens") or 0)
                out_tok = int(stats.get("output_tokens") or stats.get("completion_tokens") or 0)
            self.usage.value = {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "uncached_input_tokens": in_tok,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "total_tokens": in_tok + out_tok,
                "cost_usd": None,
                "cost_basis": "cli_reported_tokens",
            } if (in_tok or out_tok) else None
        except (ValueError, AttributeError, TypeError):
            self.usage.value = None
        return parse_gemini_output(p.stdout)


class AntigravityBackend(Backend):
    """Google Antigravity CLI (`agy`). The prompt is sent as one stream-json user message on stdin (agy has no plain
    stdin prompt), so prompt size is not limited by the OS argument cap. Runs sandboxed in an empty directory."""
    name = "antigravity"
    known_paths = ("~/.local/bin/agy", "/usr/local/bin/agy")

    def complete(self, system: str, prompt: str) -> str:
        model = getattr(self.request, "model", None) or self.model
        print_timeout = max(10, int(self.timeout))
        cmd = [self.binary, "--input-format", "stream-json", "--output-format", "stream-json",
               "--sandbox", "--disable-slash-commands", "--print-timeout", f"{print_timeout}s"]
        if model:
            cmd += ["--model", model]
        cmd.append("-p=")
        message = json.dumps({"event": "user", "message": {"role": "user", "content": _full_prompt(system, prompt)}},
                             ensure_ascii=False)
        with tempfile.TemporaryDirectory(prefix="mm-agy-") as cwd:
            # agy enforces --print-timeout itself; the process gets a little longer to report it
            p = self.run_cli(cmd, message + "\n", cwd=cwd, timeout=print_timeout + 30)
        result = parse_agy_result(p.stdout)
        if result is None:
            raise cli_failure("antigravity", p.stderr + p.stdout)
        self.usage.value = agy_usage(result.get("usage"))
        status = str(result.get("status") or "").upper()
        if status != "SUCCESS":
            detail = " ".join(str(result.get(k) or "") for k in ("error", "response")) + " " + p.stderr
            err = cli_failure("antigravity", detail)
            if err.status == 502 and "model" in detail.lower() and not (self.usage.value or {}).get("total_tokens"):
                # an unknown --model answers with the model list and no tokens: a configuration error, not retryable
                raise GatewayError(f"antigravity does not offer model {model!r}; run `agy models` and pick one.",
                                   400, "invalid_request_error")
            raise err
        return str(result.get("response") or "").strip()


def parse_agy_result(out: str) -> Optional[Dict[str, Any]]:
    """The final result of an `agy` print-mode run: the `result` event of stream-json output, or the single JSON
    object of --output-format json."""
    found = None
    text = out.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data.get("result") if isinstance(data.get("result"), dict) else data
    except ValueError:
        pass
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("event") == "result" and isinstance(ev.get("result"), dict):
            found = ev["result"]
    return found


def agy_usage(u: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(u, dict):
        return None
    uncached = int(u.get("input_tokens") or 0)
    cache_read = int(u.get("cache_read_tokens") or 0)
    out_tok = int(u.get("output_tokens") or 0) + int(u.get("thinking_tokens") or 0)
    total_in = uncached + cache_read
    if not (total_in or out_tok):
        return None
    return {"input_tokens": total_in, "output_tokens": out_tok, "uncached_input_tokens": uncached,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 0, "total_tokens": total_in + out_tok,
            "cost_usd": None, "cost_basis": "cli_reported_tokens"}


class SignInBackend(Backend):
    name = "siwc"

    def __init__(self, model: Optional[str] = None, timeout: float = 180, binary: Optional[str] = None):
        super().__init__(model=model, timeout=timeout, binary=binary or "siwc")
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
        model = getattr(self.request, "model", None) or self.model or authorized_model
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


class ChatGPTBackend(Backend):
    """ChatGPT backend: uses Sign in with ChatGPT (Responses API) when eligible/logged-in, else local Codex CLI."""
    name = "chatgpt"

    def __init__(self, model: Optional[str] = None, timeout: float = 180, binary: Optional[str] = None):
        self._codex = CodexBackend(model=model, timeout=timeout, binary=binary)
        super().__init__(model=model, timeout=timeout, binary=self._codex.binary)
        self._siwc = SignInBackend(model=model, timeout=timeout)

    def available(self) -> bool:
        return self._siwc.available() or self._codex.available()

    def complete(self, system: str, prompt: str) -> str:
        req_model = getattr(self.request, "model", None)
        max_tokens = getattr(self.request, "max_tokens", None)
        if self._siwc.available():
            self._siwc.request.model = req_model
            self._siwc.request.max_tokens = max_tokens
            out = self._siwc.complete(system, prompt)
            self.usage.value = getattr(self._siwc.usage, "value", None)
            return out
        self._codex.request.model = req_model
        self._codex.request.max_tokens = max_tokens
        out = self._codex.complete(system, prompt)
        self.usage.value = getattr(self._codex.usage, "value", None)
        return out


class MultiBackend(Backend):
    """Pools several local CLI/SIWC backends (claude, codex, gemini, antigravity, siwc) with round-robin routing.

    Failover: a 429 pauses that backend until its reset; a timeout, missing binary or any other failure marks it
    unhealthy for LLM_GATEWAY_UNHEALTHY_S (default 120 s). The backend that answered is recorded per request
    (`request.answered_by` / `request.answered_model`) so the gateway can report it and cache per backend."""
    name = "multi"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout: float = 180,
        binary: Optional[str] = None,
        backends: Optional[List[Backend]] = None,
        names: Optional[List[str]] = None,
    ):
        super().__init__(model=model, timeout=timeout, binary=binary or "multi")
        self._lock = threading.Lock()
        self._rr = 0
        if backends is not None:
            self.backends = list(backends)
        else:
            wanted = names or [
                b.strip()
                for b in (os.environ.get("LLM_GATEWAY_POOL") or "claude,codex,antigravity,gemini,siwc").split(",")
                if b.strip()
            ]
            self.backends = []
            for bname in wanted:
                cls_b = SINGLE_BACKENDS.get(bname)
                if not cls_b:
                    continue
                inst = cls_b(model=DEFAULT_MODELS.get(bname), timeout=timeout)
                if inst.available():
                    self.backends.append(inst)
        self.paused_until: Dict[str, float] = {b.name: 0.0 for b in self.backends}
        self.last_error: Dict[str, str] = {}

    def available(self) -> bool:
        return any(b.available() for b in self.backends)

    def health(self) -> List[Dict[str, Any]]:
        now = time.time()
        return [{"backend": b.name, "model": b.model, "healthy": now >= self.paused_until.get(b.name, 0.0),
                 "resume_in_s": max(0, int(self.paused_until.get(b.name, 0.0) - now)),
                 "last_error": self.last_error.get(b.name)} for b in self.backends]

    def _ordered_backends(self, req_model: Optional[str]) -> List[Backend]:
        if not self.backends:
            return []
        now = time.time()
        with self._lock:
            n = len(self.backends)
            start = self._rr % n
            self._rr += 1
            order = [self.backends[(start + i) % n] for i in range(n)]
        if req_model:
            preferred = [b for b in order if request_model(b.name, req_model) is not None]
            others = [b for b in order if b not in preferred]
            order = preferred + others
        healthy = [b for b in order if now >= self.paused_until.get(b.name, 0.0)]
        paused = [b for b in order if b not in healthy]
        return healthy + paused

    def identities(self, req_model: Optional[str]) -> List[Tuple[str, str]]:
        """(backend, model) pairs a request could be answered by, in routing order: the gateway looks the cache up
        under each, so a cached answer is found whichever backend produced it."""
        out = []
        for b in self._ordered_backends(req_model):
            out.append((b.name, str(request_model(b.name, req_model) or b.model or b.name)))
        return out

    def _mark(self, b: Backend, until: float, why: str) -> None:
        with self._lock:
            self.paused_until[b.name] = max(self.paused_until.get(b.name, 0.0), until)
            self.last_error[b.name] = why

    def complete(self, system: str, prompt: str) -> str:
        req_model = getattr(self.request, "model", None)
        max_tokens = getattr(self.request, "max_tokens", None)
        self.request.answered_by = self.request.answered_model = None
        candidates = self._ordered_backends(req_model)
        if not candidates:
            raise GatewayError("No local CLI backends available in MultiBackend pool.", 503, "upstream_unavailable")
        last_err: Optional[GatewayError] = None
        limited: List[float] = []
        for b in candidates:
            now = time.time()
            if now < self.paused_until.get(b.name, 0.0):
                if self.last_error.get(b.name) == "rate_limit":
                    limited.append(self.paused_until[b.name])
                continue
            b.request.max_tokens = max_tokens
            b.request.model = request_model(b.name, req_model)
            try:
                out = b.complete(system, prompt)
            except GatewayError as e:
                last_err = e
                if e.status == 429:
                    until = (e.retry_at if e.retry_at and e.retry_at > now else now + DEFAULT_PAUSE_S) + RESET_GRACE_S
                    self._mark(b, until, "rate_limit")
                    limited.append(until)
                else:
                    self._mark(b, now + UNHEALTHY_S, e.kind)
                continue
            except subprocess.TimeoutExpired:
                last_err = GatewayError(f"{b.name} timed out", 504, "timeout")
                self._mark(b, now + UNHEALTHY_S, "timeout")
                continue
            except (FileNotFoundError, OSError) as e:
                last_err = GatewayError(f"{b.name} CLI unavailable", 503, "upstream_unavailable")
                self._mark(b, now + UNHEALTHY_S, type(e).__name__)
                continue
            with self._lock:
                self.last_error.pop(b.name, None)
            self.usage.value = getattr(b.usage, "value", None)
            self.request.answered_by = b.name
            self.request.answered_model = b.request.model or b.model or b.name
            return out
        if limited and (last_err is None or last_err.status == 429):
            # every usable backend is rate limited: answer 429 until the first one resets
            raise GatewayError("All backends in the pool are usage limited.", 429, "rate_limit", retry_at=min(limited))
        if last_err is not None:
            raise last_err
        raise GatewayError("All backends in MultiBackend pool are unhealthy; retry shortly.", 503, "upstream_unavailable",
                           retry_at=min(self.paused_until.values()) if self.paused_until else None)


SINGLE_BACKENDS = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
    "chatgpt": ChatGPTBackend,
    "gemini": GeminiBackend,
    "antigravity": AntigravityBackend,
    "siwc": SignInBackend,
}
BACKENDS = {**SINGLE_BACKENDS, "multi": MultiBackend}


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

class Cache:
    def __init__(self, path: Optional[str]):
        self.path = path
        self.lock = threading.Lock()
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with sqlite3.connect(path, timeout=30) as c:
                c.execute("CREATE TABLE IF NOT EXISTS completions (key TEXT PRIMARY KEY, text TEXT, created REAL)")
            os.chmod(path, 0o600)

    def get(self, key: str) -> Optional[str]:
        if not self.path:
            return None
        with self.lock, sqlite3.connect(self.path, timeout=30) as c:
            row = c.execute("SELECT text FROM completions WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, text: str) -> None:
        if not self.path:
            return
        with self.lock, sqlite3.connect(self.path, timeout=30) as c:
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

    @staticmethod
    def _key(backend: str, model: str, system: str, prompt: str, temperature: float, max_tokens: Any) -> str:
        key = cache_key(backend, model, system, prompt, temperature)
        return hashlib.sha256(f"{key}|{max_tokens}".encode()).hexdigest()

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
        # The request's model when the CLI can run it (LLM_MODEL_NAME=sonnet / claude-haiku-...), else the gateway's
        # configured model. Report what the CLI actually received, never an arbitrary request string.
        self.backend.request.model = request_model(self.backend.name, body.get("model"))
        if isinstance(self.backend, MultiBackend):
            # one cache identity per backend that could answer: a cached answer is reused only for that backend
            identities = self.backend.identities(body.get("model"))
        else:
            identities = [(self.backend.name, str(self.backend.request.model or self.backend.model or self.backend.name))]
        provider, model = identities[0] if identities else (self.backend.name, self.backend.name)
        cacheable = temperature <= 0.3                                        # creative calls are not cached
        cached = None
        if cacheable:
            for ident in identities:
                cached = self.cache.get(self._key(*ident, system, prompt, temperature, max_tokens))
                if cached is not None:
                    provider, model = ident
                    break
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
            if isinstance(self.backend, MultiBackend):
                provider = getattr(self.backend.request, "answered_by", None) or provider
                model = str(getattr(self.backend.request, "answered_model", None) or model)
            with STATS_LOCK:
                STATS["upstream_calls"] += 1
                by = STATS.setdefault("by_backend", {})
                by[provider] = by.get(provider, 0) + 1
            if cacheable:
                self.cache.put(self._key(provider, model, system, prompt, temperature, max_tokens), text)
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
            return openai_response(content, model, prompt, system, usage, tool_calls=calls, provider=provider)
        return openai_response(text, model, prompt, system, usage, provider=provider)


def openai_response(text: Optional[str], model: str, prompt: str = "", system: str = "", usage: Optional[Dict[str, Any]] = None,
                    tool_calls: Optional[List[Dict[str, Any]]] = None, provider: Optional[str] = None) -> Dict[str, Any]:
    text_len = len(text or "")
    approx_in = (len(prompt) + len(system)) // 4
    u = {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0),
         "total_tokens": usage.get("total_tokens", 0)} if usage else \
        {"prompt_tokens": approx_in, "completion_tokens": text_len // 4, "total_tokens": approx_in + text_len // 4}
    return {"id": f"chatcmpl-gw{int(time.time() * 1000)}", "object": "chat.completion", "created": int(time.time()),
            "model": model,
            # the local backend that produced this answer (claude, codex, gemini, antigravity, siwc): with a multi
            # gateway it differs per request, so callers attribute results to it rather than to the gateway
            "provider": provider,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text, **({"tool_calls": tool_calls} if tool_calls else {})},
                         "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": u, "usage_source": usage.get("source", "provider") if usage else "estimated",
            "usage_breakdown": {k: usage.get(k) for k in ("uncached_input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")} if usage else None,
            "cost_usd": usage.get("cost_usd") if usage else None,
            "cost_basis": usage.get("cost_basis") if usage else None}


BACKEND_HEADER = "X-MarketMirror-Backend"


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
                    stats = json.loads(json.dumps(STATS))
                extra = {"pool": gw.backend.health()} if isinstance(gw.backend, MultiBackend) else {}
                self._send(200, {"status": "ok", "backend": gw.backend.name, "model": gw.backend.model,
                                 "available": gw.backend.available(), "auth_required": bool(gw.auth_token),
                                 "workers": gw.workers, "port": self.server.server_address[1], "pid": os.getpid(),
                                 "cache": gw.cache.path, **extra, **stats, **gw.pause_state()})
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
                answered = {BACKEND_HEADER: str(resp.get("provider") or gw.backend.name)}
                if body.get("stream"):
                    # one chunk, then [DONE]: enough for clients that insist on streaming
                    msg = resp["choices"][0]["message"]
                    delta = {"role": "assistant", "content": msg.get("content")}
                    if msg.get("tool_calls"):
                        delta["tool_calls"] = [{**c, "index": i} for i, c in enumerate(msg["tool_calls"])]
                    chunk = {"id": resp["id"], "object": "chat.completion.chunk", "created": resp["created"], "model": resp["model"],
                             "provider": resp.get("provider"),
                             "choices": [{"index": 0, "delta": delta, "finish_reason": resp["choices"][0]["finish_reason"]}]}
                    data = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode("utf-8")
                    self.send_response(200)
                    self.send_header(BACKEND_HEADER, answered[BACKEND_HEADER])
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._send(200, resp, answered)
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
                if e.status in (429, 503) and e.retry_at:
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
                                 "workers": workers, "available": backend.available(), "cache": cache_path,
                                 "binary": binary_path(backend.binary)}) + "\n")
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="OpenAI-compatible gateway over Sign in with ChatGPT or local CLI fallbacks.")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default=os.environ.get("LLM_GATEWAY", "claude"))
    ap.add_argument("--model", default=os.environ.get("LLM_GATEWAY_MODEL") or None,
                    help="model passed to the CLI (claude: sonnet, antigravity: gemini-4-argon-medium; 'default' = the CLI's own default)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LLM_GATEWAY_PORT") or DEFAULT_PORT))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("LLM_GATEWAY_WORKERS") or 2))
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("LLM_GATEWAY_TIMEOUT") or 180))
    ap.add_argument("--cache", default=os.environ.get("LLM_GATEWAY_CACHE"),
                    help="SQLite cache path ('' to disable; default: one file per port under MIROFISH_UPLOAD_DIR or backend/uploads)")
    ap.add_argument("--binary", help="path to the CLI binary (default: on PATH, then known install locations)")
    ap.add_argument("--auth-token-file", help="0600 file containing the local gateway bearer token")
    ap.add_argument("--check", action="store_true", help="print availability and exit")
    a = ap.parse_args(argv)
    model = a.model or DEFAULT_MODELS.get(a.backend)
    if model in ("default", "cli"):          # explicitly use the CLI's own default model
        model = None
    backend = BACKENDS[a.backend](model=model, timeout=a.timeout, binary=a.binary)
    if a.check:
        print(json.dumps({"backend": a.backend, "available": backend.available(), "model": backend.model,
                          "binary": binary_path(backend.binary) if a.backend not in ("siwc", "multi") else None,
                          **({"pool": [b.name for b in backend.backends]} if isinstance(backend, MultiBackend) else {})}))
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
    cache_path = default_cache_path(a.port) if a.cache is None else (a.cache or None)
    serve(backend, a.host, a.port, a.workers, cache_path, auth_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())

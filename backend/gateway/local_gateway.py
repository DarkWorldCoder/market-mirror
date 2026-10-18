#!/usr/bin/env python3
"""
local_gateway.py - run MarketMirror without an API key, on a Claude Code or ChatGPT (Codex) login.

An OpenAI-compatible server (POST /v1/chat/completions, GET /v1/models, GET /health) that fulfils every
request by running the vendor's CLI in headless mode:

    claude  ->  claude -p <prompt> --output-format json --no-session-persistence --bare [--model M]
    codex   ->  codex exec --json -o <file> <prompt>   (ChatGPT login)

Point the engine at it and nothing else changes (OASIS agents, personas, feed test, survey, pitch all use
LLM_BASE_URL):

    LLM_PROVIDER=openai
    LLM_BASE_URL=http://127.0.0.1:5055/v1
    LLM_API_KEY=gateway
    LLM_GATEWAY=claude        # or codex

    python backend/gateway/local_gateway.py --backend claude --workers 6 --port 5055

Trade-offs, honestly: each call starts a CLI process (about 3-8 s), your subscription's rate limits apply,
and both vendors allow subscription use through their own tools for your own work, not inside a product you
resell. Use an API key for teams and clients. Identical prompts are cached (SQLite), so reruns are free.
Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
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

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = os.path.join(os.path.dirname(HERE), "uploads", "gateway_cache.sqlite")
STATS = {"requests": 0, "cache_hits": 0, "failures": 0, "seconds": 0.0, "started": time.time()}
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
            turns.append(f"[Assistant]\n{content}")
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

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def complete(self, system: str, prompt: str) -> str:
        raise NotImplementedError


class ClaudeBackend(Backend):
    name = "claude"

    def complete(self, system: str, prompt: str) -> str:
        cmd = [self.binary, "-p", prompt, "--output-format", "json", "--no-session-persistence", "--bare",
               "--append-system-prompt", (GUARD + "\n\n" + system).strip(), "--disallowedTools", "*"]
        if self.model:
            cmd += ["--model", self.model]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            raise RuntimeError(f"claude exited {p.returncode}: {p.stderr.strip()[-400:] or p.stdout.strip()[-400:]}")
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
            raise RuntimeError(str(data["result"])[:400])
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
            cmd = [self.binary, "exec", "--json", "-o", out_path, "--skip-git-repo-check"]
            if self.model:
                cmd += ["-m", self.model]
            cmd.append(full)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
            if p.returncode != 0:
                raise RuntimeError(f"codex exited {p.returncode}: {p.stderr.strip()[-400:] or p.stdout.strip()[-400:]}")
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


BACKENDS = {"claude": ClaudeBackend, "codex": CodexBackend}


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
    def __init__(self, backend: Backend, workers: int = 6, cache: Optional[Cache] = None):
        self.backend = backend
        self.cache = cache or Cache(None)
        self.slots = threading.BoundedSemaphore(max(1, workers))
        self.workers = workers

    def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        system, prompt = flatten_messages(body.get("messages") or [])
        if not prompt.strip():
            raise ValueError("messages must contain a user message")
        temperature = float(body.get("temperature") or 0)
        model = str(body.get("model") or self.backend.model or self.backend.name)
        key = cache_key(self.backend.name, model, system, prompt, temperature)
        cached = self.cache.get(key) if temperature <= 0.3 else None      # creative calls are not cached
        t0 = time.time()
        if cached is not None:
            text = cached
            with STATS_LOCK:
                STATS["cache_hits"] += 1
        else:
            with self.slots:
                text = self.backend.complete(system, prompt)
            if temperature <= 0.3:
                self.cache.put(key, text)
        with STATS_LOCK:
            STATS["requests"] += 1
            STATS["seconds"] += time.time() - t0
        return openai_response(text, model, prompt, system)


def openai_response(text: str, model: str, prompt: str = "", system: str = "") -> Dict[str, Any]:
    approx_in = (len(prompt) + len(system)) // 4
    return {"id": f"chatcmpl-gw{int(time.time() * 1000)}", "object": "chat.completion", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": approx_in, "completion_tokens": len(text) // 4, "total_tokens": approx_in + len(text) // 4}}


def make_handler(gw: Gateway):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet by default
            if os.environ.get("GATEWAY_VERBOSE"):
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code: int, payload: Dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/") in ("/health", ""):
                with STATS_LOCK:
                    stats = dict(STATS)
                self._send(200, {"status": "ok", "backend": gw.backend.name, "model": gw.backend.model,
                                 "available": gw.backend.available(), "workers": gw.workers, **stats})
            elif self.path.startswith("/v1/models"):
                self._send(200, {"object": "list", "data": [{"id": gw.backend.model or gw.backend.name, "object": "model",
                                                             "owned_by": gw.backend.name}]})
            else:
                self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):
            if not self.path.startswith("/v1/chat/completions"):
                self._send(404, {"error": {"message": "not found"}})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                resp = gw.complete(body)
                if body.get("stream"):
                    # one chunk, then [DONE]: enough for clients that insist on streaming
                    chunk = {"id": resp["id"], "object": "chat.completion.chunk", "created": resp["created"], "model": resp["model"],
                             "choices": [{"index": 0, "delta": {"role": "assistant", "content": resp["choices"][0]["message"]["content"]},
                                          "finish_reason": "stop"}]}
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
            except Exception as e:  # noqa: BLE001
                with STATS_LOCK:
                    STATS["failures"] += 1
                self._send(502, {"error": {"message": str(e)[:500], "type": "backend_error"}})

    return Handler


def serve(backend: Backend, host: str, port: int, workers: int, cache_path: Optional[str]) -> None:
    gw = Gateway(backend, workers, Cache(cache_path))
    srv = ThreadingHTTPServer((host, port), make_handler(gw))
    srv.daemon_threads = True
    sys.stderr.write(json.dumps({"gateway": backend.name, "model": backend.model, "url": f"http://{host}:{port}/v1",
                                 "workers": workers, "cli_found": backend.available(), "cache": cache_path}) + "\n")
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="OpenAI-compatible gateway over the claude / codex CLIs (no API key).")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default=os.environ.get("LLM_GATEWAY", "claude"))
    ap.add_argument("--model", default=os.environ.get("LLM_GATEWAY_MODEL") or None, help="model passed to the CLI (optional)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LLM_GATEWAY_PORT") or 5055))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("LLM_GATEWAY_WORKERS") or 6))
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("LLM_GATEWAY_TIMEOUT") or 180))
    ap.add_argument("--cache", default=os.environ.get("LLM_GATEWAY_CACHE") or DEFAULT_CACHE, help="SQLite cache path ('' to disable)")
    ap.add_argument("--binary", help="path to the CLI binary (default: on PATH)")
    ap.add_argument("--check", action="store_true", help="print availability and exit")
    a = ap.parse_args(argv)
    backend = BACKENDS[a.backend](model=a.model, timeout=a.timeout, binary=a.binary)
    if a.check:
        print(json.dumps({"backend": a.backend, "cli_found": backend.available(), "binary": shutil.which(backend.binary)}))
        return 0 if backend.available() else 1
    if not backend.available():
        sys.stderr.write(f"error: '{backend.binary}' not found on PATH. Install the {a.backend} CLI and log in first.\n")
        return 1
    serve(backend, a.host, a.port, a.workers, a.cache or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())

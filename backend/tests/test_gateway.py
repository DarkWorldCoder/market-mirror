"""Local gateway: message flattening, CLI output parsing, cache, the HTTP contract with fake claude/codex binaries."""

import json
import os
import stat
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gateway"))
import local_gateway as gw  # noqa: E402


def _fake_bin(tmp_path, name, script):
    p = tmp_path / name
    p.write_text("#!/usr/bin/env bash\n" + script)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_flatten_messages_and_key():
    system, prompt = gw.flatten_messages([{"role": "system", "content": "be brief"},
                                          {"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image_url"}]},
                                          {"role": "assistant", "content": "hello"}, {"role": "user", "content": "more"}])
    assert system == "be brief" and prompt.startswith("[User]\nhi") and prompt.endswith("[Assistant]\n")
    assert gw.flatten_messages([{"role": "user", "content": "solo"}]) == ("", "solo")
    k1 = gw.cache_key("claude", "m", system, prompt, 0)
    assert k1 == gw.cache_key("claude", "m", system, prompt, 0) and k1 != gw.cache_key("codex", "m", system, prompt, 0)


def test_parse_outputs():
    assert gw.parse_claude_output(json.dumps({"type": "result", "result": "42", "is_error": False})) == "42"
    assert gw.parse_claude_output('junk\n{"result": "ok"}') == "ok"
    assert gw.parse_claude_output("plain text") == "plain text"
    with pytest.raises(RuntimeError):
        gw.parse_claude_output(json.dumps({"is_error": True, "result": "rate limited"}))
    events = "\n".join([json.dumps({"type": "item.started"}), json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
                        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "final"}})])
    assert gw.parse_codex_events(events) == "final"


def test_claude_backend_with_fake_cli(tmp_path):
    b = _fake_bin(tmp_path, "claude", 'printf \'{"type":"result","result":"echo: %s"}\' "$2"\n')
    out = gw.ClaudeBackend(binary=b, timeout=10).complete("sys", "the prompt")
    assert out == "echo: the prompt"


def test_codex_backend_with_fake_cli(tmp_path):
    # codex exec --json -o <file> --skip-git-repo-check <prompt>: write the last message to the file
    b = _fake_bin(tmp_path, "codex", 'out=""; while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; shift; fi; last="$1"; shift; done; printf "codex says: %s" "$last" > "$out"\n')
    out = gw.CodexBackend(binary=b, timeout=10).complete("", "ping")
    assert out.startswith("codex says:") and "ping" in out


def test_http_contract_and_cache(tmp_path):
    counter = tmp_path / "calls"
    b = _fake_bin(tmp_path, "claude", f'echo x >> "{counter}"; printf \'{{"result":"reply to %s"}}\' "$2"\n')
    backend = gw.ClaudeBackend(binary=b, timeout=10)
    g = gw.Gateway(backend, workers=2, cache=gw.Cache(str(tmp_path / "cache.sqlite")))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gw.make_handler(g))
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        def post(body, stream=False):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode(), r.headers.get("Content-Type")

        body = {"model": "x", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "hello"}], "temperature": 0}
        text, ctype = post(body)
        resp = json.loads(text)
        assert resp["object"] == "chat.completion" and resp["choices"][0]["message"]["content"] == "reply to hello"
        assert resp["usage"]["total_tokens"] > 0
        text2, _ = post(body)                                        # identical prompt: served from the cache
        assert json.loads(text2)["choices"][0]["message"]["content"] == "reply to hello"
        assert counter.read_text().count("x") == 1
        post({**body, "temperature": 0.9})                           # creative call: not cached
        assert counter.read_text().count("x") == 2
        stext, sctype = post({**body, "stream": True})
        assert sctype.startswith("text/event-stream") and "data: [DONE]" in stext
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as r:
            h = json.loads(r.read())
        assert h["backend"] == "claude" and h["requests"] >= 4 and h["cache_hits"] == 2   # the stream call hit the cache too
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as r:
            assert json.loads(r.read())["data"][0]["owned_by"] == "claude"
        try:
            post({"messages": []})
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()


def test_check_flag_reports_missing_cli(tmp_path):
    assert gw.main(["--backend", "codex", "--binary", str(tmp_path / "nope"), "--check"]) == 1

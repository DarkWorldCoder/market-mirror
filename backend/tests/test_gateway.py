"""Local gateway: message flattening, CLI output parsing, cache, the HTTP contract with fake claude/codex binaries."""

from types import SimpleNamespace
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


def test_claude_gateway_preserves_login_and_reports_provider_usage(monkeypatch):
    def invoke(cmd, **kwargs):
        assert "--bare" not in cmd and cmd[cmd.index("--tools") + 1] == ""
        assert "--strict-mcp-config" in cmd
        assert json.loads(cmd[cmd.index("--settings") + 1])["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "3000"
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok", "usage": {
            "input_tokens": 5, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 2,
            "output_tokens": 4}, "total_cost_usd": 0.01}), stderr="")
    monkeypatch.setattr(gw.subprocess, "run", invoke)
    backend = gw.ClaudeBackend(model="haiku")
    result = gw.Gateway(backend).complete({"model": "unused-alias", "max_tokens": 3000, "messages": [{"role": "user", "content": "hello"}]})
    assert result["model"] == "haiku" and result["usage_source"] == "provider"
    assert result["usage"]["prompt_tokens"] == 10 and result["usage"]["total_tokens"] == 14
    assert result["cost_basis"] == "cli_reported_list_cost"
    assert result["usage_breakdown"] == {"uncached_input_tokens": 5, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3}



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
        assert json.loads(text2)["usage"]["total_tokens"] == 0
        assert json.loads(text2)["usage_source"] == "local_cache"
        assert json.loads(text2)["cost_usd"] == 0 and json.loads(text2)["cost_basis"] == "no_upstream_call"
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


def test_cli_login_and_limit_errors_are_actionable_and_do_not_echo_payload():
    for detail, code in [("Not logged in · Please run /login secret-sentinel",401),
                         ("rate limit exceeded secret-sentinel",429)]:
        error = gw.cli_failure("claude", detail)
        assert error.status == code and "secret-sentinel" not in str(error)


# ---------------------------------------------------------------- tool-call emulation (OASIS agents act through tools)

TOOLS = [{"type": "function", "function": {"name": "create_post", "description": "Post something",
                                           "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}}},
         {"type": "function", "function": {"name": "do_nothing", "description": "Skip", "parameters": {"type": "object", "properties": {}}}}]


def test_tool_instructions_and_parsing():
    ins = gw.tool_instructions(TOOLS)
    assert "create_post" in ins and '"tool_calls"' in ins and "plain words" in ins
    assert "must call exactly this tool: do_nothing" in gw.tool_instructions(TOOLS, {"type": "function", "function": {"name": "do_nothing"}})
    content, calls = gw.parse_tool_reply('```json\n{"tool_calls": [{"name": "create_post", "arguments": {"content": "hi"}}]}\n```', TOOLS)
    assert content is None and calls[0]["function"]["name"] == "create_post" and json.loads(calls[0]["function"]["arguments"]) == {"content": "hi"}
    _, calls = gw.parse_tool_reply('{"name": "do_nothing", "arguments": "{}"}', TOOLS)
    assert calls and calls[0]["function"]["arguments"] == "{}"
    content, calls = gw.parse_tool_reply('{"tool_calls": [{"name": "hack", "arguments": {}}], "content": "nope"}', TOOLS)
    assert calls == [] and content == "nope"                                  # unknown tools are dropped
    assert gw.parse_tool_reply("just words", TOOLS) == ("just words", [])


def test_flatten_shows_earlier_tool_calls_and_results():
    msgs = [{"role": "user", "content": "feed"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "create_post", "arguments": "{\"content\": \"x\"}"}}]},
            {"role": "tool", "tool_call_id": "c1", "name": "create_post", "content": "{\"success\": true}"},
            {"role": "user", "content": "next round"}]
    _, prompt = gw.flatten_messages(msgs)
    assert "called create_post" in prompt and "[Tool result for create_post]" in prompt and prompt.endswith("[Assistant]\n")


def test_gateway_returns_openai_tool_calls(tmp_path):
    class B(gw.Backend):
        name = "fake"

        def complete(self, system, prompt):
            if "[Tools you can call]" not in prompt:
                return "plain answer"
            return '{"tool_calls": [{"name": "create_post", "arguments": {"content": "hello"}}]}'
    b = B()
    b.request = threading.local()
    g = gw.Gateway(b, workers=1, cache=gw.Cache(None))
    r = g.complete({"messages": [{"role": "user", "content": "go"}], "tools": TOOLS, "temperature": 0.5})
    ch = r["choices"][0]
    assert ch["finish_reason"] == "tool_calls" and ch["message"]["content"] is None
    assert ch["message"]["tool_calls"][0]["function"]["name"] == "create_post"
    r2 = g.complete({"messages": [{"role": "user", "content": "go"}], "tools": TOOLS, "tool_choice": "none"})
    assert r2["choices"][0]["finish_reason"] == "stop" and r2["choices"][0]["message"]["content"] == "plain answer"


def test_usage_limit_is_parsed_and_pauses_the_gateway(tmp_path):
    import time as _t
    now = _t.mktime((2026, 10, 19, 10, 0, 0, 0, 0, -1))
    assert _t.localtime(gw.parse_reset("You've hit your session limit · resets 12:45pm", now))[3:5] == (12, 45)
    assert gw.parse_reset("try again in 2 hours 13 minutes", now) == now + 2 * 3600 + 13 * 60
    assert gw.parse_reset("usage limit reached|1760000000", now) == 1760000000
    assert gw.parse_reset("rate limit", now) is None
    err = gw.cli_failure("claude", "You've hit your session limit · resets 12:45pm")
    assert err.status == 429 and err.retry_at

    calls = []

    class B(gw.Backend):
        name = "fake"

        def complete(self, system, prompt):
            calls.append(prompt)
            raise gw.cli_failure("claude", "You've hit your session limit · resets 12:45pm")
    b = B()
    b.request = threading.local()
    g = gw.Gateway(b, workers=1, cache=gw.Cache(None))
    body = {"messages": [{"role": "user", "content": "hi"}], "temperature": 0.9}
    with pytest.raises(gw.GatewayError) as first:
        g.complete(body)
    assert first.value.status == 429 and g.pause_state()["paused"]
    with pytest.raises(gw.GatewayError) as second:                      # paused: answered locally, no upstream call
        g.complete(body)
    assert second.value.status == 429 and len(calls) == 1
    g.paused_until = 0                                                  # reset reached: upstream is tried again
    with pytest.raises(gw.GatewayError):
        g.complete(body)
    assert len(calls) == 2


def test_http_429_carries_retry_after():
    class B(gw.Backend):
        name = "fake"

        def complete(self, system, prompt):
            raise gw.cli_failure("claude", "Claude AI usage limit reached|9999999999")
    b = B()
    b.request = threading.local()
    g = gw.Gateway(b, workers=1, cache=gw.Cache(None))
    hits_before = gw.STATS.get("limit_hits", 0)                        # STATS is shared by the module's tests
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gw.make_handler(g))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps({"messages": [{"role": "user", "content": "x"}]}).encode(),
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 429 and int(e.value.headers["Retry-After"]) > 0
    assert json.loads(e.value.read())["error"]["resets_at"]
    health = json.loads(urllib.request.urlopen(base + "/health", timeout=5).read())
    assert health["paused"] and health["limit_hits"] == hits_before + 1
    srv.shutdown()


def test_request_model_and_default():
    assert gw.request_model("claude", "sonnet") == "sonnet"
    assert gw.request_model("claude", "claude-haiku-4-5") == "claude-haiku-4-5"
    assert gw.request_model("claude", "claude") is None                 # the generic name means "the gateway's model"
    assert gw.request_model("claude", "gpt-5") is None
    assert gw.request_model("codex", "gpt-5") == "gpt-5"
    assert gw.DEFAULT_MODELS["claude"] == "sonnet"

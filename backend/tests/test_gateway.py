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
    b = _fake_bin(tmp_path, "claude", 'p=$(cat); printf \'{"type":"result","result":"echo: %s"}\' "$p"\n')
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



FAKE_CODEX = r'''
if [ "$1" = features ]; then printf 'apps                stable  true\nplugins             stable  true\nmemories            stable  true\n'; exit 0; fi
if [ "$2" = "--help" ]; then echo "--ignore-user-config --ignore-rules --ephemeral --skip-git-repo-check"; exit 0; fi
args="$*"; out=""; instr=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; shift; fi
  case "$1" in model_instructions_file=*) instr="${1#model_instructions_file=}"; instr="${instr%\"}"; instr="${instr#\"}";; esac
  shift
done
p=$(cat)
printf 'codex says: %s\nARGS %s\nCWD %s\nINSTR %s' "$p" "$args" "$PWD" "$(cat "$instr")" > "$out"
echo '{"type":"thread.started"}'
echo '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":5}}'
'''


def test_claude_output_cap_leaves_room_for_thinking(monkeypatch):
    seen = {}

    def invoke(cmd, **kwargs):
        seen["cap"] = json.loads(cmd[cmd.index("--settings") + 1])["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]
        seen["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")
    monkeypatch.setattr(gw.subprocess, "run", invoke)
    gw.Gateway(gw.ClaudeBackend(model="haiku")).complete({"max_tokens": 200, "messages": [{"role": "user", "content": "hi"}]})
    assert seen["cap"] == str(gw.CLAUDE_MIN_OUTPUT_TOKENS) and "mm-claude-" in seen["cwd"]


def test_codex_backend_with_fake_cli(tmp_path):
    # codex exec --json -o <file> ... -: the prompt arrives on stdin, the last message is written to the file
    b = _fake_bin(tmp_path, "codex", FAKE_CODEX)
    backend = gw.CodexBackend(binary=b, timeout=10)
    out = backend.complete("be a buyer", "ping")
    assert out.startswith("codex says: ping")
    args = out.split("ARGS ", 1)[1].split("\n", 1)[0]
    # no MCP servers, no user config / rules, the probed features off, prompt from stdin, an empty temp cwd
    assert "mcp_servers={}" in args and "--ignore-user-config" in args and "--ignore-rules" in args
    assert "--disable apps" in args and "--disable plugins" in args and "--disable memories" in args
    assert "--disable shell_tool" not in args                     # unknown to this codex build: not passed
    assert args.rstrip().endswith(" -") and "ping" not in args
    cwd = out.split("CWD ", 1)[1].split("\n", 1)[0]
    assert "mm-codex-" in cwd and not os.path.exists(cwd)         # removed after the call
    assert "be a buyer" in out.split("INSTR ", 1)[1] and "API relay" in out.split("INSTR ", 1)[1]
    assert backend.usage.value["input_tokens"] == 100 and backend.usage.value["cache_read_input_tokens"] == 40
    backend.request.model = "gpt-5.5"                             # the request's model is honoured
    assert "-m gpt-5.5" in backend.complete("", "x")


def test_codex_huge_prompt_rides_stdin(tmp_path):
    b = _fake_bin(tmp_path, "codex", FAKE_CODEX)
    out = gw.CodexBackend(binary=b, timeout=10).complete("", "y" * 200_000)
    assert out.count("y") >= 200_000


def test_codex_binary_found_outside_path(tmp_path, monkeypatch):
    app = tmp_path / "chatgpt" / "resources"
    app.mkdir(parents=True)
    real = _fake_bin(app, "codex", FAKE_CODEX)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(gw.CodexBackend, "known_paths", (str(tmp_path / "missing" / "codex"), str(tmp_path / "chat*" / "resources" / "codex")))
    backend = gw.CodexBackend(timeout=10)
    assert backend.binary == real and backend.available()
    assert gw.main(["--backend", "codex", "--check"]) == 0


def test_cli_missing_binary_and_timeout_become_gateway_errors(tmp_path):
    backend = gw.ClaudeBackend(binary=str(tmp_path / "nope"), timeout=5)
    with pytest.raises(gw.GatewayError) as e:
        backend.complete("", "hi")
    assert e.value.status == 503
    slow = _fake_bin(tmp_path, "claude", "sleep 5\n")
    with pytest.raises(gw.GatewayError) as e:
        gw.ClaudeBackend(binary=slow, timeout=0.5).complete("", "hi")
    assert e.value.status == 504 and e.value.kind == "timeout"


def test_http_contract_and_cache(tmp_path):
    counter = tmp_path / "calls"
    b = _fake_bin(tmp_path, "claude", f'echo x >> "{counter}"; p=$(cat); printf \'{{"result":"reply to %s"}}\' "$p"\n')
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
    assert gw.parse_reset("RESOURCE_EXHAUSTED: Individual quota reached. Resets in 160h0m44s.", now) == now + 160 * 3600 + 44
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



def test_huge_prompt_goes_over_stdin(tmp_path):
    b = _fake_bin(tmp_path, "claude", 'n=$(wc -c); printf \'{"type":"result","result":"got %s bytes"}\' "$n"\n')
    backend = gw.ClaudeBackend(binary=str(b))
    big = "x" * 200_000                                                 # > 128 KiB: too large for one argument
    assert backend.complete("short system", big).startswith("got 2000")
    assert backend.complete("s" * 150_000, "hi").startswith("got 15")   # an oversized system prompt rides in stdin


def test_gemini_chatgpt_and_multi_backends(tmp_path):
    gem_bin = _fake_bin(
        tmp_path,
        "gemini",
        'printf \'{"response":"gemini echo: namaste","stats":{"models":{"gemini-2.5-flash":{"tokens":{"prompt":12,"candidates":6,"total":18}}}}}\'\n',
    )
    gb = gw.GeminiBackend(binary=str(gem_bin), timeout=10)
    gb.request = threading.local()
    assert "namaste" in gb.complete("sys", "namaste")
    assert gb.usage.value["total_tokens"] == 18

    codex_bin = _fake_bin(tmp_path, "codex", 'out=""; while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; shift; fi; last="$1"; shift; done; printf "chatgpt-codex: %s" "$last" > "$out"\n')
    cb = gw.ChatGPTBackend(binary=str(codex_bin), timeout=10)
    cb.request = threading.local()
    assert "chatgpt-codex:" in cb.complete("", "hello")

    # MultiBackend round-robins across healthy children and fails over on 429
    class Fail429(gw.Backend):
        name = "claude"
        model = "sonnet"
        def __init__(self):
            super().__init__(model="sonnet")
        def available(self):
            return True
        def complete(self, system, prompt):
            raise gw.cli_failure("claude", "rate limit exceeded")

    mb = gw.MultiBackend(backends=[Fail429(), gb])
    out = mb.complete("sys", "fallback test")
    assert "gemini echo:" in out
    assert mb.paused_until["claude"] > 0



# ---------------------------------------------------------------- gemini, antigravity, multi, side-by-side gateways

FAKE_GEMINI = r'''
p=$(cat)
case "$p" in
  *NOTLOGGEDIN*) echo "Please set an Auth method in your settings.json or specify GEMINI_API_KEY" >&2; exit 41 ;;
  *QUOTA*) echo '{"error":{"code":429,"message":"RESOURCE_EXHAUSTED: Quota exceeded. Please retry in 25.5s."}}'; exit 1 ;;
esac
printf '{"response":"gemini: %s | %s | %s","stats":{"models":{"m":{"tokens":{"prompt":7,"candidates":3}}}}}' "$(echo "$p" | tail -n1)" "$*" "$PWD"
'''


def test_gemini_runs_without_tools_in_an_empty_dir_with_the_prompt_on_stdin(tmp_path):
    b = gw.GeminiBackend(binary=_fake_bin(tmp_path, "gemini", FAKE_GEMINI), timeout=10)
    out = b.complete("sys", "hello there")
    assert out.startswith("gemini: hello there")
    assert "--approval-mode plan" in out and "-e none" in out and "-m gemini" not in out
    assert "mm-gemini-" in out and b.usage.value["total_tokens"] == 10
    b.request.model = "gemini-2.5-pro"
    assert "-m gemini-2.5-pro" in b.complete("", "x")
    with pytest.raises(gw.GatewayError) as e:
        b.complete("", "NOTLOGGEDIN")
    assert e.value.status == 401 and e.value.kind == "authentication_error"
    with pytest.raises(gw.GatewayError) as e:
        b.complete("", "QUOTA")
    assert e.value.status == 429 and e.value.retry_at and 20 < e.value.retry_at - __import__("time").time() < 30


FAKE_AGY = r'''
args="$*"; model=""
while [ $# -gt 0 ]; do [ "$1" = "--model" ] && model="$2"; shift; done
line=$(cat)
case "$line" in
  *QUOTA*) echo '{"event":"result","result":{"status":"ERROR","response":"","error":"RESOURCE_EXHAUSTED: quota exceeded, retry in 30s","usage":{"input_tokens":0,"output_tokens":0}}}'; exit 1 ;;
esac
case "$model" in
  bad-*) echo '{"event":"result","result":{"status":"ERROR","response":"Unknown model. Available models: gemini-4-argon-medium, gpt-oss-120b-medium","usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0}}}'; exit 1 ;;
esac
echo '{"event":"init","init":{"model":"'"$model"'"}}'
printf '{"event":"result","result":{"status":"SUCCESS","response":"agy[%s] %s %s","usage":{"input_tokens":20,"output_tokens":4,"thinking_tokens":1,"cache_read_tokens":100}}}\n' "$model" "$(printf %s "$line" | head -c 3000 | tr -d '"\\')" "$args $PWD"
'''


def test_antigravity_backend_streams_the_prompt_on_stdin(tmp_path):
    b = gw.AntigravityBackend(model=gw.DEFAULT_MODELS["antigravity"], binary=_fake_bin(tmp_path, "agy", FAKE_AGY), timeout=20)
    out = b.complete("be terse", "hello agy")
    assert out.startswith("agy[gemini-4-argon-medium]") and "event: user" in out and "hello agy" in out
    assert "--sandbox" in out and "--input-format stream-json" in out and "--print-timeout 20s" in out and "mm-agy-" in out
    assert b.usage.value["input_tokens"] == 120 and b.usage.value["output_tokens"] == 5
    b.request.model = gw.request_model("antigravity", "gemini-3.8-flash-low")
    assert b.complete("", "x").startswith("agy[gemini-3.8-flash-low]")
    big = b.complete("", "z" * 300_000)                             # far above one argument's limit: fine on stdin
    assert big.startswith("agy[")
    b.request.model = "bad-model"
    with pytest.raises(gw.GatewayError) as e:
        b.complete("", "x")
    assert e.value.status == 400 and e.value.kind == "invalid_request_error"
    b.request.model = None
    with pytest.raises(gw.GatewayError) as e:
        b.complete("", "QUOTA")
    assert e.value.status == 429 and e.value.retry_at


def test_request_model_routing_per_backend():
    assert gw.request_model("antigravity", "gemini-4-argon-medium") == "gemini-4-argon-medium"
    assert gw.request_model("antigravity", "gpt-oss-120b-medium") == "gpt-oss-120b-medium"
    assert gw.request_model("antigravity", "claude-sonnet-5-5-medium") == "claude-sonnet-5-5-medium"
    assert gw.request_model("antigravity", "gemini-2.5-flash") is None
    assert gw.request_model("gemini", "gemini-4-argon-medium") is None        # an Antigravity id, not a Gemini CLI one
    assert gw.request_model("claude", "claude-sonnet-5-5-medium") is None
    assert gw.request_model("codex", "codex") is None                          # generic name: the gateway's model
    assert gw.request_model("codex", "gpt-oss-120b-medium") is None
    assert gw.request_model("multi", "gemini-4-argon-medium") == "gemini-4-argon-medium"


def test_limit_classification_needs_a_real_429():
    assert gw.cli_failure("x", "HTTP 429 Too Many Requests").status == 429
    assert gw.cli_failure("x", "status 429").status == 429
    assert gw.cli_failure("x", "processed 14290 tokens then crashed").status == 502
    assert gw.cli_failure("x", "RESOURCE_EXHAUSTED").status == 429
    assert gw.parse_reset('"retryDelay": "41s"', 1000.0) == 1041.0


class _Fake(gw.Backend):
    def __init__(self, name, reply=None, error=None):
        super().__init__(model=name + "-model", binary="true")
        self.name, self.reply, self.error, self.calls = name, reply, error, 0

    def available(self):
        return True

    def complete(self, system, prompt):
        self.calls += 1
        if self.error is not None:
            raise self.error
        self.usage.value = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        return self.reply or f"{self.name} answer"


def test_multi_fails_over_on_timeouts_missing_cli_and_errors_and_marks_unhealthy():
    import subprocess as sp
    slow = _Fake("claude", error=sp.TimeoutExpired("claude", 1))
    gone = _Fake("codex", error=FileNotFoundError("codex"))
    broken = _Fake("gemini", error=gw.GatewayError("boom", 502))
    ok = _Fake("antigravity")
    mb = gw.MultiBackend(backends=[slow, gone, broken, ok])
    assert mb.complete("", "q") == "antigravity answer"
    assert mb.request.answered_by == "antigravity" and mb.request.answered_model == "antigravity-model"
    health = {h["backend"]: h for h in mb.health()}
    assert not health["claude"]["healthy"] and health["claude"]["last_error"] == "timeout"
    assert not health["codex"]["healthy"] and not health["gemini"]["healthy"] and health["antigravity"]["healthy"]
    mb.complete("", "again")                                    # unhealthy backends are skipped, not retried
    assert slow.calls == gone.calls == broken.calls == 1 and ok.calls == 2


def test_multi_all_rate_limited_answers_429_until_the_first_reset():
    import time as _t
    a = _Fake("claude", error=gw.GatewayError("lim", 429, "rate_limit", retry_at=_t.time() + 600))
    b = _Fake("codex", error=gw.GatewayError("lim", 429, "rate_limit", retry_at=_t.time() + 300))
    mb = gw.MultiBackend(backends=[a, b])
    with pytest.raises(gw.GatewayError) as e:
        mb.complete("", "q")
    assert e.value.status == 429 and 300 < e.value.retry_at - _t.time() < 400


def test_multi_gateway_reports_the_answering_backend_and_caches_per_backend(tmp_path):
    first = _Fake("claude", error=gw.GatewayError("boom", 502))
    second = _Fake("antigravity")
    g = gw.Gateway(gw.MultiBackend(backends=[first, second]), workers=2, cache=gw.Cache(str(tmp_path / "c.sqlite")))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gw.make_handler(g))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions"
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "temperature": 0}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}), timeout=10) as r:
            resp, header = json.loads(r.read()), r.headers.get("X-MarketMirror-Backend")
        assert resp["provider"] == "antigravity" and header == "antigravity" and resp["model"] == "antigravity-model"
        first.error = None                                        # claude is back, but still paused as unhealthy
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}), timeout=10) as r:
            resp2 = json.loads(r.read())
        # the cached answer is found under the backend that produced it and is reported as that backend's
        assert resp2["usage_source"] == "local_cache" and resp2["provider"] == "antigravity" and second.calls == 1
        health = json.loads(urllib.request.urlopen(url.replace("/v1/chat/completions", "/health"), timeout=5).read())
        assert {p["backend"] for p in health["pool"]} == {"claude", "antigravity"} and health["port"] == srv.server_address[1]
    finally:
        srv.shutdown()
    # a single backend's cache key is its own name + model: another backend never reads it
    k_claude = gw.Gateway._key("claude", "sonnet", "", "hi", 0, None)
    assert k_claude != gw.Gateway._key("antigravity", "sonnet", "", "hi", 0, None)


def test_side_by_side_gateways_get_their_own_cache_files(tmp_path, monkeypatch):
    monkeypatch.setenv("MIROFISH_UPLOAD_DIR", str(tmp_path / "inst"))
    assert gw.default_cache_path(5055) == str(tmp_path / "inst" / "gateway_cache.sqlite")
    assert gw.default_cache_path(5092) == str(tmp_path / "inst" / "gateway_cache_5092.sqlite")
    assert gw.default_cache_path(5092) != gw.default_cache_path(5093)


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_two_gateways_run_at_once_with_their_own_tokens(tmp_path):
    import subprocess as sp
    import time as _t
    claude = _fake_bin(tmp_path, "claude", 'cat >/dev/null; printf \'{"type":"result","result":"from claude"}\'\n')
    agy = _fake_bin(tmp_path, "agy", FAKE_AGY)
    procs, ports = [], []
    try:
        for name, binary in (("claude", claude), ("antigravity", agy)):
            port = _free_port()
            tok = tmp_path / f"tok-{name}"
            tok.write_text(f"token-for-{name}-" + "x" * 30)
            env = {**os.environ, "MIROFISH_UPLOAD_DIR": str(tmp_path / "uploads")}
            procs.append(sp.Popen([sys.executable, gw.__file__, "--backend", name, "--binary", binary, "--port", str(port),
                                   "--auth-token-file", str(tok)], env=env, stderr=sp.DEVNULL, stdout=sp.DEVNULL))
            ports.append((name, port, tok.read_text()))
        for name, port, token in ports:
            h = None
            for _ in range(100):
                try:
                    h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read())
                    break
                except OSError:
                    _t.sleep(0.1)
            assert h and h["backend"] == name and h["cache"].endswith(f"gateway_cache_{port}.sqlite")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                         data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
            out = json.loads(urllib.request.urlopen(req, timeout=20).read())
            assert out["provider"] == name
        other = urllib.request.Request(f"http://127.0.0.1:{ports[0][1]}/v1/chat/completions",
                                       data=b'{"messages":[{"role":"user","content":"hi"}]}',
                                       headers={"Authorization": "Bearer " + ports[1][2]})
        with pytest.raises(urllib.error.HTTPError) as e:              # one gateway's token does not open another
            urllib.request.urlopen(other, timeout=5)
        assert e.value.code == 401
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)

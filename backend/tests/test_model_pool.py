"""Tests for MultiProviderPool: multi-LLM routing (Claude, ChatGPT, Codex, Gemini, Ollama) and 429 failover."""

from types import SimpleNamespace
import pytest

from app.utils.model_pool import MultiProviderPool, ProviderSlot, canonical_provider
from app.utils.openai_chat_compat import create_chat_completion, is_gemini_target


class FakeCompletions:
    def __init__(self, reply="ok", fail_429=False):
        self.reply = reply
        self.fail_429 = fail_429
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_429:
            raise RuntimeError("Error code: 429 - rate limit exceeded")
        msg = SimpleNamespace(content=f"{self.reply}:{kwargs.get('model')}")
        usage = SimpleNamespace(prompt_tokens=12, completion_tokens=6)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage)


def _fake_slot(provider: str, model: str, base_url: str, fail_429: bool = False):
    comp = FakeCompletions(reply=provider, fail_429=fail_429)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=comp),
        base_url=base_url,
    )
    client.with_options = lambda **_kw: client
    slot = ProviderSlot(provider=provider, model=model, base_url=base_url, api_key="k", client=client)
    return slot, comp


def test_canonical_provider_and_gemini_detection():
    assert canonical_provider("google", "", "gemini-2.5-flash") == "gemini"
    assert canonical_provider("chatgpt", "", "gpt-5") == "chatgpt"
    assert canonical_provider("codex", "", "gpt-5") == "codex"
    assert canonical_provider(None, "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash") == "gemini"
    assert canonical_provider(None, "https://api.anthropic.com/v1/", "claude-sonnet-4-5") == "claude"
    c = SimpleNamespace(base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    assert is_gemini_target(c, "models/gemini-2.5-flash") is True


def test_deterministic_agent_and_slot_routing():
    s_claude, c_claude = _fake_slot("claude", "claude-sonnet-4-5", "https://api.anthropic.com/v1/")
    s_gemini, c_gemini = _fake_slot("gemini", "models/gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/")
    s_chatgpt, c_chatgpt = _fake_slot("chatgpt", "gpt-5", "http://127.0.0.1:4011/v1")
    s_codex, c_codex = _fake_slot("codex", "gpt-5", "http://127.0.0.1:4011/v1")

    pool = MultiProviderPool([s_claude, s_gemini, s_chatgpt, s_codex])
    assert pool.is_multi is True
    assert pool.providers == ["claude", "gemini", "chatgpt", "codex"]

    for aid in range(8):
        resp = create_chat_completion(
            pool,
            model="default",
            messages=[{"role": "user", "content": f"hello {aid}"}],
            temperature=0.7,
            max_tokens=100,
            agent_id=aid,
        )
        expected_slot = [s_claude, s_gemini, s_chatgpt, s_codex][aid % 4]
        assert resp._mm_provider == expected_slot.provider

    # Gemini slot strips models/ prefix; ChatGPT/Codex gpt-5 slots convert max_tokens -> max_completion_tokens
    assert c_gemini.calls[0]["model"] == "gemini-2.5-flash"
    assert "max_completion_tokens" in c_chatgpt.calls[0] and "temperature" not in c_chatgpt.calls[0]
    assert "max_completion_tokens" in c_codex.calls[0]

    summ = pool.summary()
    assert summ["total_calls"] == 8
    assert summ["total_input_tokens"] == 8 * 12
    assert len(summ["slots"]) == 4


def test_429_rate_limit_failover_across_providers():
    s_claude, c_claude = _fake_slot("claude", "claude-sonnet-4-5", "https://api.anthropic.com/v1/", fail_429=True)
    s_gemini, c_gemini = _fake_slot("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/", fail_429=False)
    pool = MultiProviderPool([s_claude, s_gemini], pause_seconds=60.0)

    # Agent 0 maps to slot 0 (claude), which raises 429 -> automatically fails over to slot 1 (gemini)
    resp = create_chat_completion(
        pool,
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "test failover"}],
        max_tokens=50,
        agent_id=0,
    )
    assert resp._mm_provider == "gemini"
    assert resp._mm_model == "gemini-2.5-flash"
    assert len(c_claude.calls) == 1
    assert len(c_gemini.calls) == 1
    assert pool.summary()["slots"][0]["rate_limits"] == 1


def test_from_env_builds_claude_gemini_chatgpt_codex_pool():
    env = {
        "LLM_POOL": "claude:claude-sonnet-4-5,gemini:gemini-2.5-flash,chatgpt:gpt-5,codex:gpt-5",
        "ANTHROPIC_API_KEY": "k-ant",
        "GEMINI_API_KEY": "k-gem",
        "OPENAI_API_KEY": "k-oai",
        "CODEX_GATEWAY_URL": "http://127.0.0.1:5092/v1",
        "CODEX_GATEWAY_KEY": "k-cdx-gateway-token",
    }
    pool = MultiProviderPool.from_env(
        env=env,
        client_factory=lambda api_key, base_url: SimpleNamespace(api_key=api_key, base_url=base_url),
    )
    assert pool.providers == ["claude", "gemini", "chatgpt", "codex"]
    assert [s.model for s in pool.slots] == ["claude-sonnet-4-5", "gemini-2.5-flash", "gpt-5", "gpt-5"]
    codex = pool.slots[3]
    assert codex.api_key == "k-cdx-gateway-token" and codex.base_url == "http://127.0.0.1:5092/v1"



# ---------------------------------------------------------------- gateway labels, failover classes, pauses, caching

import json as _json
import threading as _threading
import time as _time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.utils import model_pool as mp


def test_codex_slot_never_uses_an_openai_api_key():
    env = {"LLM_POOL": "codex,claude", "OPENAI_API_KEY": "k-oai", "ANTHROPIC_API_KEY": "k-ant"}
    pool = MultiProviderPool.from_env(env=env, client_factory=lambda api_key, base_url: SimpleNamespace(api_key=api_key, base_url=base_url))
    assert pool.providers == ["claude"]                                     # no gateway configured: no codex slot
    assert all(s.api_key != "k-oai" for s in pool.slots)
    env.update({"LLM_GATEWAY": "codex", "LLM_BASE_URL": "http://127.0.0.1:5092/v1", "LLM_API_KEY": "gw-token", "LLM_PROVIDER": "openai"})
    pool = MultiProviderPool.from_env(env=env, client_factory=lambda api_key, base_url: SimpleNamespace(api_key=api_key, base_url=base_url))
    codex = next(s for s in pool.slots if s.provider == "codex")
    assert codex.api_key == "gw-token" and codex.base_url == "http://127.0.0.1:5092/v1"


def test_antigravity_gateway_slot_and_retries_off_in_a_multi_pool():
    seen = []

    def factory(api_key, base_url, **kw):
        seen.append(kw)
        return SimpleNamespace(api_key=api_key, base_url=base_url)
    env = {"LLM_POOL": "claude,antigravity", "ANTHROPIC_API_KEY": "k",
           "ANTIGRAVITY_GATEWAY_URL": "http://127.0.0.1:5093/v1", "ANTIGRAVITY_GATEWAY_KEY": "t"}
    pool = MultiProviderPool.from_env(env=env, client_factory=factory)
    assert pool.providers == ["claude", "antigravity"] and pool.slots[1].model == "gemini-4-argon-medium"
    assert all(kw.get("max_retries") == 0 for kw in seen)                  # the pool fails over; SDK retries off
    seen.clear()
    MultiProviderPool.from_env(env={"ANTHROPIC_API_KEY": "k", "LLM_PROVIDER": "claude"}, client_factory=factory)
    assert seen == [{}]                                                      # a single provider keeps SDK retries


def _health_server(backend):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            data = _json.dumps({"status": "ok", "backend": backend}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    _threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_gateway_urls_are_labelled_by_their_backend_not_openai():
    srv = _health_server("antigravity")
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        assert canonical_provider("openai", url, "antigravity") == "antigravity"
        assert canonical_provider(None, url, None) == "antigravity"
    finally:
        srv.shutdown()
    dead = "http://127.0.0.1:1/v1"                                           # nothing listening: fall back to LLM_GATEWAY
    mp._GATEWAY_LABEL_CACHE.clear()
    assert canonical_provider("openai", dead, "codex", env={"LLM_BASE_URL": dead, "LLM_GATEWAY": "codex"}) == "codex"
    mp._GATEWAY_LABEL_CACHE.clear()
    assert canonical_provider(None, "http://127.0.0.1:11434/v1", "llama3") == "ollama"
    assert canonical_provider(None, "http://127.0.0.1:51234/v1", "x", env={}) == "gateway"   # not LM Studio's 1234
    assert canonical_provider("claude", "http://127.0.0.1:5091/v1", "sonnet") == "claude"


def test_rate_limit_detection_ignores_a_bare_429_in_text():
    assert mp._is_rate_limit(RuntimeError("Error code: 429 - rate limit exceeded"))
    class StatusError(Exception):
        status_code = 429
    assert mp._is_rate_limit(StatusError("no wording at all"))
    assert not mp._is_rate_limit(RuntimeError("bad JSON near token 4291 of the reply"))
    assert not mp._is_rate_limit(RuntimeError("the ad costs 429 NPR"))

    class APITimeoutError(Exception):
        pass
    assert mp._is_rate_limit_or_transient(APITimeoutError("Request timed out."))
    assert mp._is_rate_limit_or_transient(TimeoutError())


def test_timeouts_fail_over_and_pause_the_slot_briefly():
    class TimeoutComp(FakeCompletions):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            raise TimeoutError("read timed out")
    s_a, _ = _fake_slot("claude", "claude-sonnet-4-5", "https://api.anthropic.com/v1/")
    comp = TimeoutComp()
    s_a.client.chat = SimpleNamespace(completions=comp)
    s_b, c_b = _fake_slot("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/")
    pool = MultiProviderPool([s_a, s_b])
    resp = create_chat_completion(pool, model="claude-sonnet-4-5", messages=[{"role": "user", "content": "x"}], agent_id=0)
    assert resp._mm_provider == "gemini" and pool.slots[0].timeouts == 1 and not pool.slots[0].is_healthy()
    create_chat_completion(pool, model="claude-sonnet-4-5", messages=[{"role": "user", "content": "y"}], agent_id=0)
    assert len(comp.calls) == 1                                              # paused: not called again


def test_all_slots_paused_fails_fast_without_calling_anyone():
    s_a, c_a = _fake_slot("claude", "claude-sonnet-4-5", "https://api.anthropic.com/v1/", fail_429=True)
    s_b, c_b = _fake_slot("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/", fail_429=True)
    pool = MultiProviderPool([s_a, s_b], pause_seconds=600)
    with pytest.raises(Exception):
        create_chat_completion(pool, model="m", messages=[{"role": "user", "content": "x"}], agent_id=0)
    before = len(c_a.calls) + len(c_b.calls)
    with pytest.raises(mp.PoolPausedError) as e:
        create_chat_completion(pool, model="m", messages=[{"role": "user", "content": "x"}], agent_id=1)
    assert len(c_a.calls) + len(c_b.calls) == before and mp._is_rate_limit(e.value)


def test_answering_backend_reported_by_a_multi_gateway_is_recorded():
    s, comp = _fake_slot("multi", "multi", "http://127.0.0.1:5095/v1")
    orig = comp.create

    def create(**kw):
        r = orig(**kw)
        r.provider = "antigravity"
        r.model = "gemini-4-argon-medium"
        return r
    comp.create = create
    pool = MultiProviderPool([s])
    resp = pool.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])
    assert resp._mm_provider == "antigravity" and resp._mm_model == "gemini-4-argon-medium"
    assert pool.summary()["slots"][0]["answered_by"] == {"antigravity": 1}


def test_with_options_view_shares_pauses_and_usage():
    s_a, _ = _fake_slot("claude", "claude-sonnet-4-5", "https://api.anthropic.com/v1/")
    s_b, _ = _fake_slot("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/")
    pool = MultiProviderPool([s_a, s_b])
    view = pool.with_options(timeout=60, max_retries=1)
    view.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
    assert pool.summary()["total_calls"] == 1 and view.slots is pool.slots
    assert view._client_options["max_retries"] == 0


def test_config_pool_is_built_once_per_process(monkeypatch):
    from app.config import Config
    import app.config as cfg
    cfg._POOL_CACHE.clear()
    monkeypatch.setattr(Config, "LLM_API_KEY", "k")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://api.anthropic.com/v1/")
    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude")
    p1, p2 = Config.get_model_pool(), Config.get_model_pool()
    assert p1 is p2
    monkeypatch.setenv("LLM_POOL", "claude:claude-haiku-4-5")
    assert Config.get_model_pool() is not p1                               # configuration changed: rebuilt

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
        "CODEX_API_KEY": "k-cdx",
    }
    pool = MultiProviderPool.from_env(
        env=env,
        client_factory=lambda api_key, base_url: SimpleNamespace(api_key=api_key, base_url=base_url),
    )
    assert pool.providers == ["claude", "gemini", "chatgpt", "codex"]
    assert [s.model for s in pool.slots] == ["claude-sonnet-4-5", "gemini-2.5-flash", "gpt-5", "gpt-5"]


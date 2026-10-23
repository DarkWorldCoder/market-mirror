"""Claude on the native Messages API with prompt caching (anthropic_native.py), and the marker staying away from
every other provider."""

from types import SimpleNamespace

import pytest

from app.utils import anthropic_native as an
from app.utils.model_pool import MultiProviderPool, ProviderSlot
from app.utils.openai_chat_compat import create_chat_completion


class FakeMessages:
    def __init__(self, stop="end_turn"):
        self.calls, self.stop = [], stop

    def create(self, **params):
        self.calls.append(params)
        usage = SimpleNamespace(input_tokens=40, output_tokens=12, cache_read_input_tokens=900,
                                cache_creation_input_tokens=0)
        return SimpleNamespace(id="msg_1", model=params["model"], stop_reason=self.stop, stop_details=None, usage=usage,
                               content=[SimpleNamespace(type="text", text='{"ok": true}')])


def client(stop="end_turn", effort="low"):
    fake = SimpleNamespace(messages=FakeMessages(stop))
    return an.AnthropicChatClient("k", effort=effort, _client=fake), fake.messages


def test_shared_part_is_cached_and_the_per_person_part_is_not():
    c, m = client()
    resp = c.chat.completions.create(model="claude-opus-5-5", max_tokens=500, temperature=0.9, messages=[
        {"role": "system", "content": "You write people."},
        {"role": "user", "content": "brief, rules and schema" + an.CACHE_BREAK + "1. age 30, female"}])
    p = m.calls[0]
    blocks = p["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "brief, rules and schema", "cache_control": {"type": "ephemeral"}}
    assert blocks[1] == {"type": "text", "text": "1. age 30, female"}
    assert "cache_control" not in p["system"][0]               # the user breakpoint already covers the system
    assert "temperature" not in p and p["output_config"] == {"effort": "low"} and p["max_tokens"] == 500
    assert resp.choices[0].message.content == '{"ok": true}'
    assert (resp.usage.prompt_tokens, resp.usage.cache_read_input_tokens, resp.usage.completion_tokens) == (940, 900, 12)


def test_without_a_marker_only_the_instructions_are_cached():
    c, m = client(effort="")
    c.chat.completions.create(model="claude-sonnet-5-5", messages=[
        {"role": "system", "content": "Instructions."}, {"role": "user", "content": "A unique question."}])
    p = m.calls[0]
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert p["messages"][0]["content"] == "A unique question." and "output_config" not in p


def test_a_refusal_counts_as_a_failed_call():
    c, _ = client(stop="refusal")
    with pytest.raises(RuntimeError):
        c.chat.completions.create(model="claude-opus-5-5", messages=[{"role": "user", "content": "x"}])


def test_a_claude_api_slot_uses_the_native_client_and_others_never_see_the_marker():
    pool = MultiProviderPool.from_env(env={"LLM_POOL": "claude,deepseek", "ANTHROPIC_API_KEY": "k1", "DEEPSEEK_API_KEY": "k2"})
    kinds = {s.provider: type(s.client).__name__ for s in pool.slots}
    assert kinds["claude"] == "AnthropicChatClient" and kinds["deepseek"] == "OpenAI"
    seen = []
    other = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: seen.append(kw) or "r")))
    create_chat_completion(other, model="m", messages=[{"role": "user", "content": "a" + an.CACHE_BREAK + "b"}])
    assert an.CACHE_BREAK not in seen[0]["messages"][0]["content"]
    gw = MultiProviderPool([ProviderSlot(provider="codex", model="m", base_url="http://127.0.0.1:5056/v1", api_key="t",
                                         client=other)])
    gw.for_slot(0).chat.completions.create(model="m", messages=[{"role": "user", "content": "a" + an.CACHE_BREAK + "b"}])
    assert an.CACHE_BREAK not in seen[1]["messages"][0]["content"]


def test_native_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MM_CLAUDE_NATIVE", "off")
    pool = MultiProviderPool.from_env(env={"LLM_PROVIDER": "claude", "ANTHROPIC_API_KEY": "k1"})
    assert type(pool.slots[0].client).__name__ == "OpenAI"


def test_a_gateway_placeholder_model_becomes_the_slots_real_model():
    seen = []
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **p: seen.append(p["model"]) or FakeMessages().create(**p)))
    slot = ProviderSlot(provider="claude", model="claude-sonnet-5-5", base_url="https://api.anthropic.com/v1/", api_key="k",
                        client=an.AnthropicChatClient("k", _client=fake))
    pool = MultiProviderPool([slot])
    for name in ("claude", "sonnet", "claude-sonnet-5-5"):
        pool.for_slot(0).chat.completions.create(model=name, messages=[{"role": "user", "content": "x"}])
    assert seen == ["claude-sonnet-5-5"] * 3

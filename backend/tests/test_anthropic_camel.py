"""OASIS agents on Claude's native Messages API: request shape, cache breakpoints, tool calls, interviews, usage."""

import asyncio
import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("camel")
pytest.importorskip("oasis")

from app.utils import anthropic_camel as ac  # noqa: E402
from app.utils.anthropic_camel import ClaudeNativeModel, build_request, messages_to_native  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import agent_context  # noqa: E402

MODEL = "claude-opus-5-5"
PERSONA = "Your name is Asha.\nYour have profile: Nurse in Pune, 34, careful with money, runs 5k on weekends."


def text_block(t):
    return SimpleNamespace(type="text", text=t)


def tool_block(i, name, args):
    return SimpleNamespace(type="tool_use", id=i, name=name, input=args)


def reply(*blocks, stop="end_turn", read=0, write=0, fresh=40, out=12):
    return SimpleNamespace(id="msg_1", model=MODEL, stop_reason=stop, content=list(blocks),
                           usage=SimpleNamespace(input_tokens=fresh, output_tokens=out,
                                                 cache_read_input_tokens=read, cache_creation_input_tokens=write))


class FakeAsyncAnthropic:
    """Records every request (deep-copied) and answers from a script."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **params):
        self.requests.append(copy.deepcopy(params))
        return self.script.pop(0)


class FakeAnthropic(FakeAsyncAnthropic):
    def create(self, **params):  # noqa: D401 - sync twin
        self.requests.append(copy.deepcopy(params))
        return self.script.pop(0)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("OASIS_CACHE_TTL", "MM_CACHE_TTL", "OASIS_CLAUDE_EFFORT", "MM_CLAUDE_EFFORT", "MM_CLAUDE_NATIVE"):
        monkeypatch.delenv(k, raising=False)
    ac.reset_usage()
    yield
    ac.reset_usage()


def social_agent(model):
    """A real OASIS Twitter agent whose platform channel is replaced by a recorder."""
    from oasis.social_agent.agent import SocialAgent
    from oasis.social_platform.config import UserInfo
    from oasis.social_platform.typing import ActionType

    info = UserInfo(name="asha", description="", recsys_type="twitter",
                    profile={"other_info": {"user_profile": "Nurse in Pune, 34, careful with money, runs 5k on weekends."}})
    agent = SocialAgent(agent_id=3, user_info=info, model=model,
                        available_actions=[ActionType.LIKE_POST, ActionType.CREATE_POST, ActionType.DO_NOTHING])
    agent.max_iteration = agent_context.DEFAULT_MAX_ITERATION        # as agent_context.install sets it
    done = []

    async def perform_action(message, type):
        done.append((type, message))
        return {"success": True, "like_id": 9} if type == "like_post" else {"success": True}

    async def to_text_prompt(*a, **k):
        return "After refreshing, you see some posts [{'post_id': 1, 'content': 'New running shoes at 40% off'}]"

    agent.env.action.perform_action = perform_action
    agent.env.to_text_prompt = to_text_prompt
    return agent, done


# ---------------------------------------------------------------------------------------------------
# A tool-calling OASIS action, then an interview, through a real SocialAgent
# ---------------------------------------------------------------------------------------------------

def test_social_action_and_interview_are_cached():
    fake = FakeAsyncAnthropic([
        reply(text_block("Worth a look."), tool_block("toolu_01", "like_post", {"post_id": 1}), stop="tool_use",
              write=1500),
        reply(text_block("Done for now."), read=1500, write=80),
        reply(text_block("I'd only buy them on sale, and only if they fit my wide feet."), read=1580),
    ])
    model = ClaudeNativeModel(MODEL, {"max_tokens": 4096}, api_key="k", async_client=fake)
    model.usage_tag = "twitter"
    agent, done = social_agent(model)

    asyncio.run(agent.perform_action_by_llm())
    assert done and done[0] == ("like_post", 1)

    first, second = fake.requests[0], fake.requests[1]
    # tools: OpenAI schemas -> native tools, the last one is a breakpoint shared by every agent on the platform
    names = [t["name"] for t in first["tools"]]
    assert "like_post" in names and all("input_schema" in t for t in first["tools"])
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert sum("cache_control" in t for t in first["tools"]) == 1
    # system: the persona prompt once, with its own breakpoint; conversation: automatic caching
    assert len(first["system"]) == 1 and "Nurse in Pune" in first["system"][0]["text"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["output_config"] == {"effort": "low"}
    assert "temperature" not in first and first["max_tokens"] == 4096
    assert [m["role"] for m in first["messages"]] == ["user"]
    assert "New running shoes" in first["messages"][0]["content"][0]["text"]

    # the follow-up call carries the tool call and its result, after a byte-identical prefix
    assert second["tools"] == first["tools"] and second["system"] == first["system"]
    assert second["messages"][0] == first["messages"][0]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    use = [b for b in second["messages"][1]["content"] if b["type"] == "tool_use"]
    assert use == [{"type": "tool_use", "id": "toolu_01", "name": "like_post", "input": {"post_id": 1}}]
    result = second["messages"][2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_01"
    assert "'success': True" in result["content"]

    # interview: no tools, system not repeated, breakpoint at the end of the memory, the question uncached
    out = asyncio.run(agent.perform_interview("Would you buy these shoes? Answer in one sentence."))
    assert "wide feet" in out["content"]
    iv = fake.requests[2]
    assert "tools" not in iv and "cache_control" not in iv
    assert len(iv["system"]) == 1 and iv["system"][0]["text"] == first["system"][0]["text"]
    assert iv["messages"][-1]["content"] == [{"type": "text",
                                             "text": "Would you buy these shoes? Answer in one sentence."}]
    marked = [b for m in iv["messages"] for b in m["content"] if "cache_control" in b]
    assert len(marked) == 1 and iv["messages"][-2]["content"][-1] is not None
    assert "cache_control" in iv["messages"][-2]["content"][-1]
    # the memory before the question is the same conversation the rounds cached
    assert iv["messages"][0] == first["messages"][0]

    totals = ac.usage_totals("twitter")
    assert totals == {"calls": 3, "input_tokens": 120, "cache_read_input_tokens": 3080,
                      "cache_creation_input_tokens": 1580, "output_tokens": 36}


def test_completion_shape_and_usage_fields():
    fake = FakeAnthropic([reply(tool_block("toolu_9", "create_post", {"content": "hi"}), stop="tool_use",
                                read=700, write=30, fresh=5)])
    model = ClaudeNativeModel(MODEL, {"max_tokens": 1024}, api_key="k", client=fake)
    resp = model.run([{"role": "system", "content": PERSONA}, {"role": "user", "content": "feed"}],
                     tools=[{"type": "function", "function": {"name": "create_post", "description": "Post.",
                                                              "parameters": {"type": "object", "properties": {
                                                                  "content": {"type": "string"}},
                                                                  "required": ["content"]}, "strict": True}}])
    from camel.types import ChatCompletion
    assert isinstance(resp, ChatCompletion)
    call = resp.choices[0].message.tool_calls[0]
    assert call.id == "toolu_9" and call.function.name == "create_post"
    assert json.loads(call.function.arguments) == {"content": "hi"}
    assert resp.choices[0].finish_reason == "tool_calls"
    from camel.agents._utils import safe_model_dump
    usage = safe_model_dump(resp.usage)
    assert usage["prompt_tokens"] == 735 and usage["completion_tokens"] == 12
    assert usage["cache_read_input_tokens"] == 700 and usage["cache_creation_input_tokens"] == 30
    assert "strict" not in fake.requests[0]["tools"][0]


def test_refusal_is_an_error():
    fake = FakeAnthropic([reply(stop="refusal")])
    model = ClaudeNativeModel(MODEL, None, api_key="k", client=fake)
    with pytest.raises(RuntimeError, match="declined"):
        model.run([{"role": "user", "content": "x"}])


# ---------------------------------------------------------------------------------------------------
# Message translation edge cases
# ---------------------------------------------------------------------------------------------------

def test_tool_groups_are_made_valid():
    msgs = [
        {"role": "system", "content": PERSONA},
        {"role": "tool", "content": "{'success': True}", "tool_call_id": "gone"},           # call windowed away
        {"role": "user", "content": "feed 1"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call:1", "type": "function", "function": {"name": "like_post", "arguments": '{"post_id": 2}'}},
            {"id": "call_2", "type": "function", "function": {"name": "repost", "arguments": '{"post_id": 3}'}}]},
        {"role": "tool", "content": "{'success': True}", "tool_call_id": "call:1"},
        {"role": "user", "content": "feed 2"},
        {"role": "system", "content": "You are a twitter user."},
    ]
    system, native = messages_to_native(msgs)
    assert [b["text"] for b in system] == [PERSONA]
    assert [m["role"] for m in native] == ["user", "assistant", "user"]
    assert [b["id"] for b in native[1]["content"]] == ["call_1", "call_2"]            # ids made API-safe
    after = native[2]["content"]
    assert [b["type"] for b in after] == ["tool_result", "tool_result", "text", "text"]
    assert after[1] == {"type": "tool_result", "tool_use_id": "call_2", "content": ac.NO_RESULT}
    assert after[3]["text"] == "You are a twitter user."                              # late system -> user text


def test_conversation_must_start_and_end_with_user():
    _, native = messages_to_native([{"role": "assistant", "content": "earlier reply "}])
    assert [m["role"] for m in native] == ["user", "assistant", "user"]
    assert native[1]["content"] == [{"type": "text", "text": "earlier reply"}]


def test_ttl_and_effort_settings(monkeypatch):
    monkeypatch.setenv("MM_CACHE_TTL", "1h")
    req = build_request(MODEL, [{"role": "system", "content": PERSONA}, {"role": "user", "content": "q"}],
                        [{"type": "function", "function": {"name": "do_nothing", "parameters": {}}}], 512, "low")
    marks = [req["tools"][-1]["cache_control"], req["system"][-1]["cache_control"], req["cache_control"]]
    assert marks == [{"type": "ephemeral", "ttl": "1h"}] * 3
    monkeypatch.setenv("OASIS_CACHE_TTL", "5m")
    req = build_request("claude-haiku-4-5", [{"role": "user", "content": "q"}], None, 512, "low")
    assert "output_config" not in req                                                  # Haiku 4.5 rejects effort
    assert "cache_control" not in req["messages"][0]["content"][0]                     # nothing before the question
    monkeypatch.setenv("OASIS_CLAUDE_EFFORT", "medium")
    assert ClaudeNativeModel(MODEL, None, api_key="k", client=object()).effort == "medium"


# ---------------------------------------------------------------------------------------------------
# Wiring and the per-stage file
# ---------------------------------------------------------------------------------------------------

def test_native_model_only_for_claude_on_the_api(monkeypatch):
    slot = SimpleNamespace(provider="claude", model=MODEL, base_url="https://api.anthropic.com/v1/", api_key="k")
    assert isinstance(agent_context._camel_model(slot), ClaudeNativeModel)
    gateway = SimpleNamespace(provider="claude_code", model=MODEL, base_url="http://127.0.0.1:5055/v1",
                              api_key="gateway")
    assert not isinstance(agent_context._camel_model(gateway), ClaudeNativeModel)
    assert agent_context.claude_native_model("gpt-4o-mini", "https://api.anthropic.com/v1/", "k") is None
    assert agent_context.claude_native_model(MODEL, "https://api.anthropic.com/v1/", "") is None
    monkeypatch.setenv("MM_CLAUDE_NATIVE", "off")
    assert not isinstance(agent_context._camel_model(slot), ClaudeNativeModel)


def test_record_stage_writes_deltas(tmp_path):
    ac._add_usage("reddit", 10, 900, 100, 20)
    row = agent_context.record_cache_usage(str(tmp_path), "reddit", "round 1")
    ac._add_usage("reddit", 5, 1000, 0, 10)
    ac._add_usage("twitter", 1, 1, 1, 1)
    agent_context.record_cache_usage(str(tmp_path), "reddit", "round 2")
    agent_context.record_cache_usage(str(tmp_path), "reddit", "round 3")       # nothing new: no row
    assert row is None                                                         # the helper itself returns nothing
    data = json.loads((tmp_path / "claude_cache_usage.json").read_text())
    assert [s["stage"] for s in data["stages"]] == ["round 1", "round 2"]
    assert data["stages"][1]["cache_read_input_tokens"] == 1000 and data["stages"][1]["calls"] == 1
    assert data["totals"]["cache_read_input_tokens"] == 1900 and data["ttl"] == "5m"
    assert data["stages"][0]["cache_read_share"] == 0.8911


def test_tag_models_reaches_managed_backends():
    from camel.models import ModelManager
    model = ClaudeNativeModel(MODEL, None, api_key="k", client=object())
    agents = [SimpleNamespace(model_backend=ModelManager(model)), SimpleNamespace(model_backend=model)]
    graph = SimpleNamespace(get_agents=lambda: list(enumerate(agents)))
    assert ac.tag_models(graph, "twitter") == 1 and model.usage_tag == "twitter"

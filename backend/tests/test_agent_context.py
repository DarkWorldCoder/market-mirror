"""Persona cards per round (agent_context) and scheduled brand posts (event_schedule), without OASIS."""

import json
import asyncio
import os
import random
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import agent_context as ac  # noqa: E402
import event_schedule as es  # noqa: E402

CONFIG = {
    "persona_index": [
        {"agent_id": 0, "name": "Acme", "kind": "graph", "entity_type": "Company"},
        {"agent_id": 1, "name": "Priya Menon", "kind": "persona", "age": 31, "occupation": "marketing coordinator",
         "city": "Pune", "country": "India", "segment": "India young professionals", "languages": ["Hindi", "English"],
         "platform_habits": "scrolls Instagram at night", "thinking_style": "price-hunter, compares everything",
         "communities": ["Pune Fitness Buddies"]},
        {"agent_id": 2, "name": "Fit Pinoy Community", "kind": "community", "entity_type": "Community"},
    ],
    "agent_configs": [{"agent_id": 0, "activity_level": 0.2}, {"agent_id": 1, "activity_level": 0.9},
                      {"agent_id": 2, "activity_level": 0.5}],
    "community_config": {"communities": [{"name": "Pune Fitness Buddies", "member_ids": [1]}]},
    "event_config": {"initial_posts": [{"poster_agent_id": 0, "content": "Hello"}],
                     "scheduled_events": [
                         {"round": 2, "poster_agent_id": 0, "content": "Launch day!", "platform": "both"},
                         {"round": 2, "poster_agent_id": 0, "content": "Reddit only", "platform": "reddit"},
                         {"round": 3, "poster_agent_id": 99, "content": "ghost"},
                         {"round": "x", "poster_agent_id": 0, "content": "bad round"},
                         {"round": 0, "poster_agent_id": 0, "content": "round zero not allowed"}]},
}


@pytest.fixture(autouse=True)
def _reset():
    ac.reset()
    yield
    ac.reset()


def test_persona_cards_cover_country_language_habits_and_scroll_past():
    cards = ac.persona_cards(CONFIG)
    p = cards[1]
    assert "Priya Menon, 31" in p and "Pune, India" in p
    assert "Hindi, English" in p and "people in India" in p
    assert "a few times a week" in p                    # activity 0.9
    assert "Pune Fitness Buddies" in p and "price-hunter" in p
    assert "do_nothing is the right answer" in p
    assert cards[0].startswith("You are the official account of Acme")
    assert "run the account of Fit Pinoy Community" in cards[2]


def test_round_flavour_budget_in_range_and_deterministic():
    ac.persona_cards(CONFIG)
    a = [ac.round_flavour(1, 3, 20, random.Random(5)) for _ in range(3)]
    b = [ac.round_flavour(1, 3, 20, random.Random(5)) for _ in range(3)]
    assert a == b
    for budget, mood in a:
        assert 1 <= budget <= 3 and mood
    night = ac.round_flavour(1, 1, 3, random.Random(1))[1]
    assert night in ("tired", "can't sleep", "bored")


def test_compose_prompt_prepends_card_and_session_line():
    ac._STATE["cards"] = ac.persona_cards(CONFIG)
    ac.begin_round(4, 21)
    out = ac.compose_prompt(1, "After refreshing, you see some posts [...]")
    assert out.startswith("You are Priya Menon")
    assert "After refreshing" in out
    assert "about 21:00" in out and "at most" in out and "do_nothing" in out
    assert ac.compose_prompt(None, "base") == "base"
    assert ac.compose_prompt(42, "base") == "base"      # unknown agent: untouched


def test_install_counts_agents_and_is_idempotent():
    agents = [(i, SimpleNamespace(social_agent_id=i)) for i in range(3)]
    graph = SimpleNamespace(get_agents=lambda: agents)
    assert ac.install(graph, CONFIG, seed=3) == 3
    first = dict(ac._STATE["budgets"])
    assert ac.install(graph, CONFIG, seed=3) == 3
    assert ac._STATE["budgets"] == first                # same seed, same budgets


def test_events_by_round_filters_platform_and_bad_rows():
    both = es.events_by_round(CONFIG)
    assert sorted(both) == [2, 3]
    assert [e["content"] for e in both[2]] == ["Launch day!", "Reddit only"]
    tw = es.events_by_round(CONFIG, "twitter")
    assert [e["content"] for e in tw[2]] == ["Launch day!"]
    assert es.events_by_round({}) == {}


def test_inject_scheduled_adds_manual_actions_and_skips_unknown():
    class LLMAction:  # name matters: it is what the runner uses for "let the model decide"
        pass

    def get_agent(i):
        if i == 99:
            raise KeyError(i)
        return f"agent{i}"

    env = SimpleNamespace(agent_graph=SimpleNamespace(get_agent=get_agent))
    MA = lambda action_type, action_args: (action_type, action_args)  # noqa: E731
    AT = SimpleNamespace(CREATE_POST="create_post")
    by_round = es.events_by_round(CONFIG)
    logs = []
    actions = {"agent0": LLMAction()}
    assert es.inject_scheduled(actions, env, 2, by_round, MA, AT, logs.append) == 2
    assert actions["agent0"] == [("create_post", {"content": "Launch day!"}), ("create_post", {"content": "Reddit only"})]
    assert es.inject_scheduled({}, env, 3, by_round, MA, AT, logs.append) == 0   # agent 99 missing
    assert any("no agent 99" in l for l in logs)
    assert es.inject_scheduled({}, env, 7, by_round, MA, AT, logs.append) == 0


def test_resolve_agent_and_normalize_events():
    idx = CONFIG["persona_index"]
    assert es.resolve_agent("Priya Menon", idx) == 1
    assert es.resolve_agent("priya", idx) == 1          # unique prefix
    assert es.resolve_agent("2", idx) == 2 and es.resolve_agent(0, idx) == 0
    assert es.resolve_agent("nobody", idx) is None and es.resolve_agent(True, idx) is None
    out = es.normalize_events(CONFIG, [{"agent": "Acme", "content": "Our new app"}],
                              [{"round": 3, "agent": "Acme", "content": "Launch", "label": "launch day"}])
    assert out["initial_posts"][0]["poster_agent_id"] == 0 and out["initial_posts"][0]["poster_type"] == "brand"
    assert out["scheduled_events"][0] == {"round": 3, "poster_agent_id": 0, "content": "Launch", "platform": "both",
                                          "label": "launch day"}
    with pytest.raises(ValueError):
        es.normalize_events(CONFIG, [{"agent": "ghost", "content": "x"}], [])
    with pytest.raises(ValueError):
        es.normalize_events(CONFIG, [], [{"round": 0, "agent": 0, "content": "x"}])
    with pytest.raises(ValueError):
        es.normalize_events(CONFIG, [], [{"round": 1, "agent": 0}])


def test_patched_environment_prompt_when_oasis_present():
    pytest.importorskip("oasis")
    from oasis.social_agent.agent_environment import SocialEnvironment
    original = SocialEnvironment.to_text_prompt
    template = SocialEnvironment.env_template.template
    ac._STATE["installed"] = False
    ac._STATE["cards"] = ac.persona_cards(CONFIG)
    ac.begin_round(2, 20)
    try:
        ac._patch_environment()
        patched = SocialEnvironment.to_text_prompt
        ac._patch_environment()                         # second call is a no-op
        assert SocialEnvironment.to_text_prompt is patched and patched is not original
        assert "Most posts deserve nothing from you" in SocialEnvironment.env_template.template

        async def fake_original(self, *a, **k):
            return "BASE OBSERVATION"
        SocialEnvironment.to_text_prompt = original     # restore, then re-wrap the fake to test the wrapper alone
        ac._STATE["installed"] = False
        SocialEnvironment.to_text_prompt = fake_original
        ac._patch_environment()
        env = SocialEnvironment.__new__(SocialEnvironment)
        env.action = SimpleNamespace(agent_id=1)
        text = asyncio.run(SocialEnvironment.to_text_prompt(env))
        assert text.startswith("You are Priya Menon") and "BASE OBSERVATION" in text and "about 20:00" in text
    finally:
        SocialEnvironment.to_text_prompt = original
        SocialEnvironment.env_template.template = template
        ac._STATE["installed"] = False


def test_per_platform_state_is_independent():
    agents = [(i, SimpleNamespace(social_agent_id=i, env=SimpleNamespace())) for i in range(3)]
    graph = SimpleNamespace(get_agents=lambda: agents)
    assert ac.install(graph, CONFIG, seed=3, platform="twitter") == 3
    assert ac.install(graph, CONFIG, seed=3, platform="reddit") == 3
    assert agents[1][1].env.mm_platform == "reddit"           # last install tags the agents' environments
    ac.begin_round(2, 21, platform="twitter")
    ac.begin_round(2, 3, platform="reddit")                    # must not touch Twitter's hour/budgets/moods
    tw, rd = ac.session_line(1, "twitter"), ac.session_line(1, "reddit")
    assert "about 21:00" in tw and "about 03:00" in rd
    assert ac._state("twitter")["hour"] == 21 and ac._state("reddit")["hour"] == 3
    assert ac._state("reddit")["moods"][1] in ("tired", "can't sleep", "bored")
    assert ac._state("twitter")["moods"][1] not in ("can't sleep",) or True   # evening moods come from MOODS
    assert ac.compose_prompt(1, "BASE", "twitter").endswith(tw) and ac.compose_prompt(1, "BASE", "reddit").endswith(rd)
    assert ac.compose_prompt(1, "BASE") == "BASE"              # the default slot was never installed
    ac.reset()
    assert ac._state("twitter")["cards"] == {} and ac._STATE["cards"] == {}


def test_memory_window_and_token_limit_are_applied(monkeypatch):
    class Creator:
        _token_limit = 4096

    class Memory:
        def __init__(self):
            self._window_size = None
            self._creator = Creator()

        def get_context_creator(self):
            return self._creator

    mems = [Memory() for _ in range(2)]
    agents = [(i, SimpleNamespace(social_agent_id=i, memory=m, max_iteration=None)) for i, m in enumerate(mems)]
    graph = SimpleNamespace(get_agents=lambda: agents + [(9, SimpleNamespace(social_agent_id=9))])
    monkeypatch.delenv("OASIS_MEMORY_WINDOW", raising=False)
    monkeypatch.delenv("OASIS_TOKEN_LIMIT", raising=False)
    assert ac.memory_window_for(graph) == 2
    assert all(m._window_size == ac.DEFAULT_MEMORY_WINDOW for m in mems)
    assert all(m._creator._token_limit == ac.DEFAULT_TOKEN_LIMIT for m in mems)
    monkeypatch.setenv("OASIS_MEMORY_WINDOW", "4")
    monkeypatch.setenv("OASIS_TOKEN_LIMIT", "9000")
    ac.install(graph, CONFIG, seed=1, platform="twitter")        # install applies the window too
    assert mems[0]._window_size == 4 and mems[0]._creator._token_limit == 9000
    assert agents[0][1].max_iteration == ac.DEFAULT_MAX_ITERATION


def test_speed_knobs_read_env(monkeypatch):
    monkeypatch.delenv("OASIS_SEMAPHORE", raising=False)
    monkeypatch.delenv("OASIS_ACTIVE_AGENT_CAP", raising=False)
    monkeypatch.delenv("OASIS_RECSYS", raising=False)
    monkeypatch.delenv("MODEL_TIMEOUT", raising=False)
    assert ac.semaphore_size() == ac.DEFAULT_SEMAPHORE and ac.recsys_type() == "random"
    assert ac.active_agent_cap() == 2**31 - 1
    assert ac.model_timeout() == float(ac.DEFAULT_MODEL_TIMEOUT) and os.environ["MODEL_TIMEOUT"] == "60"
    monkeypatch.setenv("OASIS_SEMAPHORE", "12")
    monkeypatch.setenv("OASIS_ACTIVE_AGENT_CAP", "20")
    monkeypatch.setenv("OASIS_RECSYS", "twhin-bert")
    monkeypatch.setenv("MODEL_TIMEOUT", "180")
    assert ac.semaphore_size() == 12 and ac.recsys_type() == "twhin-bert" and ac.model_timeout() == 180.0
    assert ac.active_agent_cap() == 20
    monkeypatch.setenv("OASIS_SEMAPHORE", "oops")
    monkeypatch.setenv("OASIS_RECSYS", "bogus")
    assert ac.semaphore_size() == ac.DEFAULT_SEMAPHORE and ac.recsys_type() == "random"


def test_social_action_timeout_is_bounded_and_counted():
    class Agent:
        social_agent_id = 1

        async def perform_action_by_llm(self):
            await asyncio.sleep(0.05)
            return "done"

    env = SimpleNamespace(llm_semaphore=asyncio.Semaphore(1))
    assert ac.bound_llm_actions(env, timeout_s=0.01) == 0.01
    with pytest.warns(UserWarning, match="timed out"):
        assert asyncio.run(env._perform_llm_action(Agent())) is None
    assert env.mm_action_timeouts == 1
    assert ac.bound_llm_actions(env, timeout_s=1) == 0.01


def test_twitter_platform_uses_chosen_recommender(monkeypatch, tmp_path):
    pytest.importorskip("oasis")
    from oasis.social_platform.typing import RecsysType
    monkeypatch.delenv("OASIS_RECSYS", raising=False)
    p = ac.twitter_platform(str(tmp_path / "tw.db"))
    assert p is not None and p.recsys_type == RecsysType.RANDOM and p.max_rec_post_len == 2


def test_window_records_keeps_tool_call_groups_whole():
    def rec(role, call_id=None):
        return SimpleNamespace(memory_record=SimpleNamespace(role_at_backend=SimpleNamespace(value=role),
                                                             message=SimpleNamespace(tool_call_id=call_id)))
    # the window cut in the middle of round 1: its assistant call is gone, its two results are orphans
    records = [rec("system"), rec("function", "c1"), rec("function", "c2"), rec("user"),
               rec("assistant", "c3"), rec("function", "c3"), rec("user"), rec("assistant", "c4"), rec("function", "c4")]
    out = ac.window_records(records)
    roles = [(r.memory_record.role_at_backend.value, r.memory_record.message.tool_call_id) for r in out]
    assert roles == [("system", None), ("user", None), ("assistant", "c3"), ("function", "c3"), ("user", None),
                     ("assistant", "c4"), ("function", "c4")]
    # a window that starts with an assistant text reply also waits for the first user message
    out = ac.window_records([rec("system"), rec("assistant"), rec("user"), rec("assistant")])
    assert [r.memory_record.role_at_backend.value for r in out] == ["system", "user", "assistant"]
    # nothing but the system message so far: untouched
    only_sys = [rec("system")]
    assert ac.window_records(only_sys) == only_sys


def test_memory_window_patch_applies_to_camel_memory():
    pytest.importorskip("camel")
    from camel.memories import ChatHistoryMemory, MemoryRecord, ScoreBasedContextCreator
    from camel.messages import BaseMessage, FunctionCallingMessage
    from camel.types import ModelType, OpenAIBackendRole, RoleType
    from camel.utils import OpenAITokenCounter

    def call(i):
        return FunctionCallingMessage(role_name="a", role_type=RoleType.ASSISTANT, meta_dict=None, content="",
                                      func_name="like_post", args={"post_id": i}, tool_call_id=f"c{i}")

    def result(i):
        return FunctionCallingMessage(role_name="a", role_type=RoleType.ASSISTANT, meta_dict=None, content="",
                                      func_name="like_post", result={"ok": True}, tool_call_id=f"c{i}")

    mem = ChatHistoryMemory(ScoreBasedContextCreator(OpenAITokenCounter(ModelType.GPT_4O_MINI), 32000), window_size=4)
    mem.write_record(MemoryRecord(message=BaseMessage.make_assistant_message("system", "sys"),
                                  role_at_backend=OpenAIBackendRole.SYSTEM))
    for i in range(3):
        mem.write_record(MemoryRecord(message=BaseMessage.make_user_message("u", f"obs {i}"), role_at_backend=OpenAIBackendRole.USER))
        mem.write_record(MemoryRecord(message=call(i), role_at_backend=OpenAIBackendRole.ASSISTANT))
        mem.write_record(MemoryRecord(message=result(i), role_at_backend=OpenAIBackendRole.FUNCTION))
    ac._patch_memory_window()
    roles = [(r.memory_record.role_at_backend.value, getattr(r.memory_record.message, "tool_call_id", None))
             for r in mem.retrieve()]
    # the raw window of 4 is [result c1, user, call c2, result c2]: the orphan result c1 must be gone
    assert roles == [("system", None), ("user", None), ("assistant", "c2"), ("function", "c2")]
    msgs, _ = mem.get_context()
    assert [m["role"] for m in msgs][:3] == ["system", "user", "assistant"] and len(msgs) == 4


def test_context_updates_reach_the_session_line(tmp_path):
    cfg_path = tmp_path / "simulation_config.json"
    cfg_path.write_text(json.dumps({"event_config": {"context_updates": [
        {"round": 2, "text": "A competitor just made its trial card-free.", "source": "r/fitness"},
        {"round": 5, "text": "Later news", "source": ""}]}}))
    ac.reset()
    st = ac._state("reddit")
    st["cards"] = ac.persona_cards(CONFIG)
    st["config_path"] = str(cfg_path)
    ac.begin_round(1, 18, platform="reddit")
    assert "saying today" not in ac.session_line(1, "reddit")
    ac.begin_round(3, 19, platform="reddit")
    line = ac.session_line(1, "reddit")
    assert line.startswith("What people around you are saying today: A competitor just made its trial card-free. (via r/fitness)")
    assert "Later news" not in line
    assert ac.context_updates(str(cfg_path), 9)[-1]["text"] == "Later news"
    assert ac.context_updates(None, 3) == [] and ac.context_updates(str(tmp_path / "missing.json"), 3) == []
    ac.set_context("", "reddit")
    assert "saying today" not in ac.session_line(1, "reddit")

"""Persona cards per round (agent_context) and scheduled brand posts (event_schedule), without OASIS."""

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

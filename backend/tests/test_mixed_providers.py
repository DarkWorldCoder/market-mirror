"""Mixed providers in one market: each person is written, interviewed, played and answered by the same provider."""

import os
import sys
from types import SimpleNamespace

import pytest

from app.services import persona_planner
from app.utils import model_pool
from app.utils.model_pool import MultiProviderPool, ProviderSlot

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import agent_context  # noqa: E402


class Down(Exception):
    status_code = 503


class Fake:
    def __init__(self, name, fail=0):
        self.name, self.fail, self.calls = name, fail, 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls += 1
        if self.calls <= self.fail:
            raise Down("service unavailable")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))], usage=None,
                               model=kw.get("model"))


def pool(*fails, strict=False):
    names = ("claude_code", "codex", "antigravity")
    slots = [ProviderSlot(provider=n, model=f"{n}-model", base_url=f"http://127.0.0.1:{5055 + i}/v1", api_key="t",
                          client=Fake(n, fails[i] if i < len(fails) else 0)) for i, n in enumerate(names)]
    p = MultiProviderPool(slots)
    p.strict = strict
    return p


def test_every_provider_writes_the_same_number_of_people():
    sizes = [5] * 199 + [3, 2, 4]
    shares = persona_planner.provider_shares(sizes, 3)
    totals = [sum(s for s, k in zip(sizes, shares) if k == i) for i in range(3)]
    assert max(totals) - min(totals) <= 5 and sum(totals) == sum(sizes)
    assert persona_planner.provider_shares([5, 5], 1) == [0, 0]


def test_people_are_answered_by_the_provider_that_wrote_them():
    p = pool()
    people = [{"agent_id": 7, "model_provider": "claude"}, {"agent_id": 8, "model_provider": "antigravity"},
              {"agent_id": 9, "model_provider": "codex"}]
    view = p.with_people(people)
    assert view.for_agent(7).provider == "claude_code"          # the gateway slot and its backend are one family
    assert view.for_agent(8).provider == "antigravity" and view.for_agent("9").provider == "codex"
    assert view.with_options(timeout=5).for_agent(8).provider == "antigravity"
    view.for_agent(8).chat.completions.create(model="x", messages=[])
    assert p.slots[2].client.calls == 1 and p.slots[0].client.calls == 0
    assert p.for_agent(7).provider == p.slots[7 % 3].provider    # the shared pool is not changed


def test_strict_pool_retries_the_same_provider_and_never_substitutes(monkeypatch):
    monkeypatch.setattr(model_pool.time, "sleep", lambda s: None)
    p = pool(0, 2, strict=True)
    resp = p.for_slot(1).chat.completions.create(model="x", messages=[])
    assert resp._mm_provider == "codex" and p.slots[1].client.calls == 3 and p.slots[0].client.calls == 0
    p.slots[1].paused_until = 0
    p2 = pool(0, 9, strict=True)
    with pytest.raises(Down):
        p2.for_slot(1).chat.completions.create(model="x", messages=[])
    assert p2.slots[0].client.calls == 0 and p2.slots[2].client.calls == 0


def test_default_pool_still_fails_over():
    p = pool(0, 9)
    resp = p.for_slot(1).chat.completions.create(model="x", messages=[])
    assert resp._mm_provider in ("antigravity", "claude_code")


def test_interviews_go_to_the_writer():
    from test_fast_population import FakePool
    fp = FakePool()
    ents = []
    for i, prov in enumerate(["codex"] * 3 + ["claude_code"] * 2 + ["antigravity"]):
        ents.append(SimpleNamespace(name=f"P{i}", labels=[persona_planner.PERSONA_LABEL],
                                    attributes={"model_provider": prov, persona_planner.SYNTHETIC_PROFILE_KEY: {"persona": "x"}}))
    n = persona_planner.run_interviews(fp, "m", ents, "ctx", probes=False)
    assert n == 6
    assert sorted(fp.used) == ["antigravity", "claude_code", "codex"]      # one interview call per writer
    assert all(e.attributes.get("interview") for e in ents)


def test_simulation_agents_get_their_writers_model():
    env = {"LLM_POOL": "claude_code,codex,antigravity",
           "CLAUDE_CODE_GATEWAY_URL": "http://127.0.0.1:5055/v1", "CLAUDE_CODE_GATEWAY_KEY": "a",
           "CODEX_GATEWAY_URL": "http://127.0.0.1:5056/v1", "CODEX_GATEWAY_KEY": "b",
           "ANTIGRAVITY_GATEWAY_URL": "http://127.0.0.1:5057/v1", "ANTIGRAVITY_GATEWAY_KEY": "c"}
    agents = [SimpleNamespace(social_agent_id=i, model_backend=None, model_type=None) for i in range(5)]
    graph = SimpleNamespace(get_agents=lambda: [(a.social_agent_id, a) for a in agents])
    cfg = {"persona_index": [{"agent_id": 0, "model_provider": "codex"}, {"agent_id": 1, "model_provider": "antigravity"},
                             {"agent_id": 2, "model_provider": "claude"}]}
    made = []
    counts = agent_context.assign_provider_models(graph, cfg, env=env,
                                                  make_model=lambda s: made.append(s.provider) or SimpleNamespace(
                                                      model_type=s.model, provider=s.provider))
    assert made == ["claude_code", "codex", "antigravity"]
    assert [a.mm_provider for a in agents[:3]] == ["codex", "antigravity", "claude_code"]
    assert sum(counts.values()) == 5
    assert agent_context.assign_provider_models(graph, cfg, env={"LLM_PROVIDER": "claude", "LLM_API_KEY": "k"}) == {}

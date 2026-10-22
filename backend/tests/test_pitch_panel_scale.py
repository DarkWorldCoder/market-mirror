"""Large runs: the pitch survives a failed batch and mixes providers per batch; the analyst panel uses the pool
normally (no provider slot) and reads at most about MAX_MATERIAL_CHARS of material."""

import json
import re
from collections import Counter
from types import SimpleNamespace

from app.services import analyst_panel as ap
from app.services import pitch as ps


def _people():
    provs = ["claude"] * 6 + ["codex"] * 3 + ["gemini_cli"] * 3      # gemini_cli is the gemini family
    return [{"agent_id": i, "name": f"P{i}", "segment": "Everyone", "model_provider": p} for i, p in enumerate(provs)]


def test_batches_mix_providers_in_proportion():
    people = _people()
    order = ps.provider_mixed(people)
    assert sorted(p["agent_id"] for p in order) == list(range(12))
    family = {"claude": "claude", "codex": "codex", "gemini_cli": "gemini"}
    for i in range(0, 12, 4):
        mix = Counter(family[p["model_provider"]] for p in order[i:i + 4])
        assert mix == {"claude": 2, "codex": 1, "gemini": 1}
    claude = [p["agent_id"] for p in order if p["model_provider"] == "claude"]
    assert claude == sorted(claude)                                  # order within a provider is kept
    plain = [{"agent_id": i} for i in range(5)]
    assert ps.provider_mixed(plain) == plain                         # no providers: the order is unchanged


T1 = json.dumps({"reply": "Hmm.", "verdict": "maybe", "interest": 5, "trust": 5, "objection": "Too pricey",
                 "objection_type": "price", "decision_role": "I decide alone"})
T2 = json.dumps({"reply": "Fair.", "verdict": "yes", "moved": "yes", "next_step_you_accept": "a trial"})


def test_pitch_survives_a_failed_batch_and_asks_turn_two_only_of_people_who_answered():
    people = _people()
    batches, turn2_asked = [], []
    calls = {"n": 0}

    def interview_batch(items):
        calls["n"] += 1
        batches.append([it["agent_id"] for it in items])
        if calls["n"] == 2:
            raise TimeoutError("等待命令响应超时 (600s)")              # the IPC wait ran out for this batch
        second = [it for it in items if "Same conversation" in it["prompt"]]
        turn2_asked.extend(it["agent_id"] for it in second)
        return {it["agent_id"]: (T2 if it in second else T1) for it in items}

    out = ps.run(interview_batch, people, "Hi", {"price": "Cheaper than a coffee."}, batch=4)
    failed = set(batches[1])
    assert len(failed) == 4 and out["failed_batches"] == 1 and "超时" in out["failed_batch_errors"][0]
    assert out["people_pitched"] == 12 and out["answered"] == 8
    assert out["unanswered"] == {"turn1": 4, "turn2": 0}
    assert not failed & set(turn2_asked) and len(turn2_asked) == 8     # turn 2 only for real turn-1 answers
    rows = {r["agent_id"]: r for r in out["people"]}
    assert all(rows[a]["turn1"] is None and rows[a]["turn2"] is None for a in failed)
    assert [r["agent_id"] for r in out["people"]] == list(range(12))  # the result keeps the people's own order
    for b in batches[:3]:                                              # every turn-1 batch mixes providers
        assert len({people[a]["model_provider"] for a in b}) == 3


def test_pitch_counts_a_failed_turn_two_batch():
    people = _people()[:4]

    def interview_batch(items):
        if any("Same conversation" in it["prompt"] for it in items):
            raise RuntimeError("environment closed")
        return {it["agent_id"]: T1 for it in items}

    out = ps.run(interview_batch, people, "Hi", {"*": "What would make it a yes?"}, batch=8)
    assert out["answered"] == 4 and out["failed_batches"] == 1 and out["unanswered"] == {"turn1": 0, "turn2": 4}
    assert all(r["turn2"] is None for r in out["people"])


ANALYST = {"headline": "h", "sentiment": 10, "purchase_intent_signal": 5, "best_audience": "Students",
           "best_message": "#1", "themes": [{"theme": "price", "weight": 6, "evidence": "too pricey"}],
           "objections": [], "opportunities": [], "risks": [], "recommendation": "test", "confidence": 5,
           "verdict": "iterate", "success_probability": 40, "evidence_gaps": ""}


class _Slot:
    def __init__(self, fail=False):
        self.fail = fail
        self.prompts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.with_options = lambda **_kw: self

    def create(self, **kw):
        self.prompts.append(kw["messages"][-1]["content"])
        if self.fail:
            raise RuntimeError("Error code: 503 - overloaded")
        msg = SimpleNamespace(content=json.dumps(ANALYST))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)


def _strict_pool(monkeypatch, gemini_fails=True):
    from app.utils.model_pool import MultiProviderPool, ProviderSlot
    monkeypatch.setenv("LLM_POOL_STRICT", "1")
    slots = {"claude": _Slot(), "codex": _Slot(), "gemini": _Slot(fail=gemini_fails)}
    pool = MultiProviderPool([ProviderSlot("claude", "claude-sonnet-4-5", "http://127.0.0.1:5055/v1", "k", slots["claude"]),
                              ProviderSlot("codex", "gpt-5", "http://127.0.0.1:5056/v1", "k", slots["codex"]),
                              ProviderSlot("gemini", "gemini-2.5-flash", "http://127.0.0.1:5057/v1", "k", slots["gemini"])])
    assert pool.strict
    return pool, slots


def test_panel_uses_the_pool_without_a_provider_slot(monkeypatch):
    pool, slots = _strict_pool(monkeypatch)
    pinned = []

    def no_slot(i):
        pinned.append(i)
        raise AssertionError("an analyst was pinned to a provider slot")

    monkeypatch.setattr(pool, "for_slot", no_slot)
    material = ap.normalize_material({"survey": [{"segment": "Students", "text": "too pricey"}]})
    res = ap.run_panel(pool, "claude-sonnet-4-5", material, "Which audience?", n=5)
    assert pinned == []
    # the failing provider is failed over instead of failing the analysts pinned to it
    assert res["consensus"]["analysts_ok"] == 5 and res["consensus"]["analysts_failed"] == 0
    assert {a["provider"] for a in res["analysts"]} <= {"claude", "codex"}
    assert slots["claude"].prompts and slots["codex"].prompts
    assert res["material_cut"] == {} and res["material_note"] == ""


def test_panel_trims_material_to_the_cap_and_says_what_was_cut(monkeypatch):
    pool, slots = _strict_pool(monkeypatch, gemini_fails=False)
    long = "x" * 480
    material = ap.normalize_material({
        "context": "Acme, a practice-test app",
        "posts": [{"segment": "Students", "text": f"post {i} short"} for i in range(20)],
        "comments": [{"segment": "Parents", "text": f"comment {i} {long}"} for i in range(200)],
        "survey": [{"segment": "Students", "text": f"survey {i} {long}"} for i in range(300)]})
    assert len(ap._render(material)) > 240_000
    res = ap.run_panel(pool, "claude-sonnet-4-5", material, "Which audience?", n=3)
    prompts = [p for s in slots.values() for p in s.prompts]
    assert len(prompts) == 3
    for p in prompts:
        rendered = p.split("Be concise:")[0]
        assert len(rendered) < ap.MAX_MATERIAL_CHARS + 1_000         # brief, lens and note on top of ~80k
        assert "Note: The material was too long" in p and "of 300 buyer survey answers" in p
        assert "post 0 short" in p and "post 19 short" in p          # the short list is kept whole
    cut = res["material_cut"]
    assert "posts" not in cut and cut["survey"]["of"] == 300 and 0 < cut["survey"]["kept"] < 300
    assert cut["comments"]["of"] == 200 and 0 < cut["comments"]["kept"] < 200
    assert res["material_counts"]["survey"] == 300 and res["material_sent"]["survey"] == cut["survey"]["kept"]
    kept = [int(m) for m in re.findall(r"survey (\d+) x", prompts[0])]
    assert kept[0] == 0 and kept[-1] >= 270                           # sampled across the list, not just its head
    assert ap.fit_material(material, 10**7) == (material, {})

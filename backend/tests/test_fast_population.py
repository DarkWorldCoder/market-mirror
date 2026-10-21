"""Fast population: cards in big batches, salvage of missing rows, per-provider lanes, a cache, an interviewed sample."""

import json
import re
import threading
from types import SimpleNamespace

import pytest

from app.services import fast_population as fp
from app.services import persona_planner as pp


class CardClient:
    """Answers card prompts (rows carry their slot number) and interview prompts; can drop or fail rows."""

    def __init__(self, drop_first=(), fail_segment=None):
        self.calls = []
        self.drop_first = set(drop_first)       # slot numbers left out of the first answer that asks for them
        self.dropped = set()
        self.fail_segment = fail_segment
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        user = kw["messages"][1]["content"]
        with self.lock:
            self.calls.append(user)
        if self.fail_segment and f"Segment: {self.fail_segment};" in user:
            raise TimeoutError("Request timed out.")
        if user.startswith("This is a life interview"):
            names = re.findall(r"^\d+\. ([^:]+):", user, re.M)
            body = {"interviews": [{"name": n, "answers": [{"q": f"Q{i}", "a": "a"} for i in range(1, 13)],
                                    "summary": f"I am {n}."} for n in names]}
        elif user.startswith("Second part of a life interview"):
            body = {"people": []}
        else:
            nums = [int(n) for n in re.findall(r"^(\d+)\. age \d+", user, re.M)]
            rows = []
            for n in nums:
                with self.lock:
                    if n in self.drop_first and n not in self.dropped:
                        self.dropped.add(n)
                        continue
                rows.append({"i": n, "name": f"Person {abs(hash(user)) % 997}-{n}", "occ": "clerk", "att": "unsure",
                             "con": ["price"], "voice": "short and dry", "ask": "sister", "spd": "slow",
                             "deal": ["card upfront"], "trust": ["friends"], "spare": "INR 2000"})
            body = {"people": rows}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)))], usage=None)


def seg(label="India students", count=10, **kw):
    return {"label": label, "count": count, "country": "India", "age_min": 18, "age_max": 24,
            "entity_type": "Student", **kw}


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("MM_POPULATION_CACHE", str(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(pp, "RETRY_PAUSE_S", 0)


def test_cards_for_everyone_and_missing_rows_are_asked_again_alone():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=25)], "depth": "fast", "interview": False})
    client = CardClient(drop_first={8, 17})          # only the first batch (20 people) has slots 8 and 17
    ents = pp.generate_personas(client, "m", spec, "req", "ctx")
    assert len(ents) == 25
    card_calls = [c for c in client.calls if c.startswith("Write")]
    assert len(card_calls) == 3                 # 20 + 5, then only slots 8 and 17 of the first batch again
    retry = next(c for c in card_calls if c.startswith("Write 2 distinct"))
    assert re.findall(r"^(\d+)\. age", retry, re.M) == ["8", "17"]
    e = ents[0]
    assert e.attributes["depth"] == "card"
    assert "How I decide: asks sister" in e.attributes[pp.SYNTHETIC_PROFILE_KEY]["persona"]
    assert e.attributes["bde"]["evaluation"]["dealbreakers"] == ["card upfront"]


def test_a_failing_segment_is_left_out_not_invented():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=6), seg("India parents", count=4, age_min=35, age_max=50,
                                                                    entity_type="Parent")],
                                     "depth": "fast", "interview": False})
    ents = pp.generate_personas(CardClient(fail_segment="India parents"), "m", spec, "req", "ctx")
    assert len(ents) == 6 and {e.attributes["segment"] for e in ents} == {"India students"}


def test_only_a_stratified_sample_is_interviewed():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=40)], "depth": "fast", "interview_share": 0.1,
                                     "probes": False})
    client = CardClient()
    ents = pp.generate_personas(client, "m", spec, "req", "ctx")
    deep = [e for e in ents if e.attributes.get("depth") == "interviewed"]
    assert len(deep) == 4 and all(e.attributes.get("interview") for e in deep)
    assert sum(1 for c in client.calls if c.startswith("This is a life interview")) == 1


def test_auto_depth_switches_above_the_threshold(monkeypatch):
    monkeypatch.setattr(pp, "FAST_ABOVE", 10)
    client = CardClient()
    pp.generate_personas(client, "m", pp.PersonaSpec.from_dict({"segments": [seg(count=12)], "interview": False,
                                                              "depth": "auto"}), "req", "ctx")
    assert client.calls[0].startswith("Write 12 distinct people")
    full = CardClient()
    pp.generate_personas(full, "m", pp.PersonaSpec.from_dict({"segments": [seg(count=12)], "interview": False}),
                         "req", "ctx")
    assert full.calls[0].startswith("Write 4 distinct synthetic people")      # the older method (full depth) is the default
    with pytest.raises(ValueError):
        pp.PersonaSpec.from_dict({"segments": [seg()], "depth": "deep"})


def test_a_rerun_reuses_cached_cards():
    spec_d = {"segments": [seg(count=20)], "depth": "fast", "interview": False, "seed": 11}
    first = CardClient()
    a = pp.generate_personas(first, "m", pp.PersonaSpec.from_dict(spec_d), "req", "ctx")
    second = CardClient()
    b = pp.generate_personas(second, "m", pp.PersonaSpec.from_dict(spec_d), "req", "ctx")
    assert second.calls == [] and [e.name for e in a] == [e.name for e in b]


def test_lane_halves_on_overload_and_grows_back():
    lane = fp.Lane("codex", 4)
    lane.acquire()
    lane.release(ok=False, overloaded=True)
    assert lane.limit == 2
    for _ in range(4):
        lane.acquire()
        lane.release(ok=True)
    assert lane.limit == 3


def test_interview_sample_covers_every_segment_and_provider():
    ents = [SimpleNamespace(attributes={"segment": s, "model_provider": p}) for s in "AB" for p in ("x", "y") for _ in range(30)]
    sample = fp.interview_sample(ents, 0.1, min_per_cell=2)
    cells = {(e.attributes["segment"], e.attributes["model_provider"]) for e in sample}
    assert len(sample) == 12 and len(cells) == 4


class FakePool:
    """Three provider slots; each answers like CardClient and records which provider answered."""

    def __init__(self):
        self.slots = [SimpleNamespace(provider=p, model=f"{p}-m") for p in ("claude_code", "codex", "antigravity")]
        self.inner = CardClient()
        self.used = []

    def slot_for_provider(self, name):
        return next((i for i, s in enumerate(self.slots) if s.provider == name), None)

    def for_slot(self, i):
        slot = self.slots[i % 3]

        def create(**kw):
            self.used.append(slot.provider)
            resp = self.inner.create(**kw)
            resp._mm_provider, resp._mm_model = slot.provider, slot.model
            return resp
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                               provider=slot.provider, model_name=slot.model, base_url="")


def test_every_provider_writes_exactly_its_share():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=25), seg("India parents", count=25, age_min=35, age_max=50,
                                                                     entity_type="Parent"),
                                                  seg("India workers", count=25, age_min=25, age_max=40)],
                                     "depth": "fast", "interview": False})
    ents = pp.generate_personas(FakePool(), "m", spec, "req", "ctx")
    by = {}
    for e in ents:
        by[e.attributes["model_provider"]] = by.get(e.attributes["model_provider"], 0) + 1
    assert by == {"claude_code": 25, "codex": 25, "antigravity": 25}

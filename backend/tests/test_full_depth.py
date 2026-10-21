"""Full depth (the older method) on the fast engine: persona, life interview and follow-ups for everyone, chained per
batch, with numbered rows, re-asks for missing people only, and the cache."""

import json
import re
import threading
from types import SimpleNamespace

from app.services import persona_planner as pp


class DeepClient:
    """Answers persona, interview and follow-up prompts in the compact numbered format; can drop or fail rows."""

    def __init__(self, drop=(), fail_segment=None):
        self.calls = []
        self.drop = set(drop)                  # ("persona"|"interview"|"probe", name-or-number) dropped once
        self.dropped = set()
        self.fail_segment = fail_segment
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def _once(self, key):
        with self.lock:
            if key in self.drop and key not in self.dropped:
                self.dropped.add(key)
                return True
        return False

    def create(self, **kw):
        user = kw["messages"][1]["content"]
        with self.lock:
            self.calls.append(user)
        if user.startswith("Write"):
            if self.fail_segment and f"Segment: {self.fail_segment}\n" in user:
                raise TimeoutError("Request timed out.")
            seg = re.search(r"^Segment: (.+)$", user, re.M).group(1)
            ages = re.findall(r"^(\d+)\. age (\d+)", user, re.M)
            rows = []
            for n, age in ages:
                name = f"{seg} person {age}-{n}-{len(user) % 97}"
                if self._once(("persona", f"{seg}:{age}")):
                    continue
                rows.append({"i": int(n), "name": name, "occupation": f"job {age} {n}", "attitude": "unsure",
                             "persona": f"{name} is a fictional person."})
            body = {"personas": rows}
        elif user.startswith("This is a life interview"):
            people = re.findall(r"^(\d+)\. ([^:]+):", user, re.M)
            rows = [{"i": int(n), "a": [f"answer {q} by {name}" for q in range(1, 13)], "phone": "Redmi 9",
                     "data_plan": "prepaid", "summary": f"I am {name}."}
                    for n, name in people if not self._once(("interview", name))]
            body = {"interviews": rows}
        else:
            nums = re.findall(r"\[person (\d+)\]", user)
            body = {"people": [{"i": int(n), "p": ["follow-up one", "follow-up two"],
                                "bde": {"b": {"who": "a busy person"}, "d": {"ask": "sister", "spd": "slow"},
                                        "e": {"spare": "INR 2000", "deal": ["card upfront"]}}} for n in nums]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)))], usage=None)


def seg(label="India students", count=10, **kw):
    return {"label": label, "count": count, "country": "India", "age_min": 18, "age_max": 60,
            "entity_type": "Student", **kw}


def spec(**kw):
    return pp.PersonaSpec.from_dict({"segments": [seg()], "seed": 3, **kw})


def test_everyone_gets_persona_interview_follow_ups_and_card():
    ents = pp.generate_personas(DeepClient(), "m", spec(), "req", "ctx")
    people = [e for e in ents if pp.PERSONA_LABEL in e.labels]
    assert len(people) == 10
    for e in people:
        a = e.attributes
        assert len([x for x in a["interview"] if x["q"].startswith("Q")]) == 12
        assert [x["a"] for x in a["interview"] if x["q"].startswith("P")] == ["follow-up one", "follow-up two"]
        assert a["bde"]["decision_procedure"]["who_they_ask"] == "sister"
        assert a["bde"]["evaluation"]["monthly_discretionary"] == "INR 2000"
        persona = a[pp.SYNTHETIC_PROFILE_KEY]["persona"]
        assert "In their own words: I am" in persona and "How I decide:" in persona
        assert a["depth"] == "interviewed"


def test_missing_people_are_asked_again_on_their_own(monkeypatch):
    monkeypatch.setenv("MM_POPULATION_CACHE", "off")          # both runs must reach the model
    first = pp.generate_personas(DeepClient(), "m", spec(), "req", "ctx")
    victim = first[2]
    client = DeepClient(drop={("persona", "India students:" + str(first[1].attributes[pp.SYNTHETIC_PROFILE_KEY]["age"])),
                              ("interview", victim.name)})
    ents = pp.generate_personas(client, "m", spec(), "req", "ctx")
    assert len(ents) == 10 and all(e.attributes.get("interview") for e in ents)
    singles = [c for c in client.calls if c.startswith("Write 1 distinct") or c.startswith("This is a life interview with 1 ")]
    assert len(singles) >= 1


def test_a_failing_segment_is_left_out_and_nobody_is_invented():
    s = pp.PersonaSpec.from_dict({"segments": [seg(count=6), seg("India parents", count=5, entity_type="Parent")],
                                  "seed": 3})
    ents = pp.generate_personas(DeepClient(fail_segment="India parents"), "m", s, "req", "ctx")
    assert len(ents) == 6 and {e.attributes["segment"] for e in ents} == {"India students"}
    assert not any(e.name.startswith("India parents ") for e in ents)


def test_a_rerun_is_answered_from_the_cache():
    a = pp.generate_personas(DeepClient(), "m", spec(), "req", "ctx")
    again = DeepClient()
    b = pp.generate_personas(again, "m", spec(), "req", "ctx")
    assert again.calls == [] and [e.name for e in a] == [e.name for e in b]


def test_prompts_are_lean_but_keep_the_older_content():
    slots = pp.demographic_slots(pp.PersonaSegment.from_dict(seg()), __import__("random").Random(1), {})[:3]
    p = pp._persona_prompt(pp.PersonaSegment.from_dict(seg()), slots, "req", "ctx", (), (), numbers=[1, 2, 3])
    assert '"i": N' in p and "compact JSON" in p and "at least 150" in p and '"age": N' not in p
    card = {"i": 1, "name": "Asha", "age": 30}
    iv = pp._interview_prompt([card], "ctx")
    assert '"a": ["answer to Q1"' in iv and '"q": "Q1"' not in iv and "Q12." in iv
    pr = pp._probe_prompt([card], {"Asha": [{"q": "Q1", "a": "x"}]}, {"Asha": ["why?"]}, [], "ctx")
    assert "[person 1]" in pr and '"spd"' in pr and '"p": ["answer to P1"' in pr


# ------------------------------------------------------------------ review fixes

class FlakyRows(DeepClient):
    """First answer for a person is incomplete: an 11-answer interview, a follow-up without a card, a persona
    without its paragraph."""

    def __init__(self, kind):
        super().__init__()
        self.kind, self.bad_once = kind, set()

    def create(self, **kw):
        resp = super().create(**kw)
        body = json.loads(resp.choices[0].message.content)
        key = {"interview": "interviews", "probe": "people", "persona": "personas"}[self.kind]
        rows = body.get(key) or []
        if rows and key in body and ("interviews" in body or "people" in body and self.kind == "probe"
                                     or "personas" in body and self.kind == "persona"):
            r = rows[0]
            tag = json.dumps(sorted(r.items(), key=lambda x: x[0])[:2], default=str)
            with self.lock:
                first = tag not in self.bad_once
                self.bad_once.add(tag)
            if first:
                if self.kind == "interview":
                    r["a"] = r["a"][:11]
                elif self.kind == "probe":
                    r.pop("bde", None)
                else:
                    r.pop("persona", None)
        resp.choices[0].message.content = json.dumps(body)
        return resp


def _complete(e):
    a = e.attributes
    return (len([x for x in a.get("interview", []) if x["q"].startswith("Q")]) == 12 and a.get("bde")
            and a[pp.SYNTHETIC_PROFILE_KEY]["persona"])


def test_incomplete_rows_are_asked_again_not_accepted(monkeypatch):
    monkeypatch.setenv("MM_POPULATION_CACHE", "off")
    for kind in ("interview", "probe", "persona"):
        client = FlakyRows(kind)
        ents = pp.generate_personas(client, "m", spec(), "req", "ctx")
        assert len(ents) == 10 and all(_complete(e) for e in ents), kind
        assert any(re.search(r"with 1 |Write 1 distinct|Second part of a life interview with 1 ", c) for c in client.calls), kind


def test_an_error_while_building_a_prompt_costs_one_batch_not_the_run(monkeypatch):
    real = pp._interview_prompt
    doomed = []
    lock = threading.Lock()

    def broken(people, context, voices=None):
        with lock:
            if not doomed:
                doomed.append(people[0]["name"])          # the first batch to reach its interview always fails
            bad = any(p["name"] == doomed[0] for p in people)
        if bad:
            raise KeyError("sentiment")
        return real(people, context, voices)
    monkeypatch.setattr(pp, "_interview_prompt", broken)
    ents = pp.generate_personas(DeepClient(), "m", spec(), "req", "ctx")
    assert len(ents) == 10                                    # everyone written is kept
    assert any(not e.attributes.get("interview") for e in ents)
    assert all(e.attributes["depth"] == ("interviewed" if e.attributes.get("interview") else "profile") for e in ents)


def test_voices_without_sentiment_and_odd_languages_do_not_break_prompts():
    from app.services import research
    assert research.pick_voices([{"text": "too pricey", "source": "reddit"}, {"no_text": 1}], 2)
    card = pp._interview_card(SimpleNamespace(name="A", attributes={"languages": [{"lang": "Hindi"}, None],
                                                                      pp.SYNTHETIC_PROFILE_KEY: {}}))
    assert card["languages"] == ["Hindi"]
    pp._interview_prompt([{**card, "i": 1}], "ctx", [{"text": "too pricey"}])


def test_the_country_is_asked_when_the_segment_has_none():
    s = pp.PersonaSegment.from_dict(seg(country=""))
    slots = pp.demographic_slots(s, __import__("random").Random(1), {})[:2]
    assert '"country": "..."' in pp._persona_prompt(s, slots, "req", "ctx", (), (), numbers=[1, 2])
    s2 = pp.PersonaSegment.from_dict(seg())
    assert '"country": "..."' not in pp._persona_prompt(s2, slots, "req", "ctx", (), (), numbers=[1, 2])


class SameJob(DeepClient):
    def create(self, **kw):
        resp = super().create(**kw)
        body = json.loads(resp.choices[0].message.content)
        for r in body.get("personas") or []:
            r["occupation"] = "tailor"
        resp.choices[0].message.content = json.dumps(body)
        return resp


def test_duplicate_jobs_are_marked_the_same_way_every_run_and_reruns_are_cached():
    a = pp.generate_personas(SameJob(), "m", spec(cities=["Pune"]), "req", "ctx")
    again = SameJob()
    b = pp.generate_personas(again, "m", spec(cities=["Pune"]), "req", "ctx")
    assert again.calls == []
    assert [e.attributes["occupation"] for e in a] == [e.attributes["occupation"] for e in b]
    assert len({e.attributes["occupation"] for e in a}) > 1


def test_fix_duplicates_counts_only_real_changes_and_can_keep_cities():
    import random
    ents = [SimpleNamespace(labels=[pp.PERSONA_LABEL], attributes={"segment": "S", "occupation": "tailor", "city": c,
                                                                   pp.SYNTHETIC_PROFILE_KEY: {}})
            for c in ("Pune", "Pune", "Delhi")]
    assert pp.fix_duplicates(ents, random.Random(1), move_city=False) == 1
    assert [e.attributes["city"] for e in ents] == ["Pune", "Pune", "Delhi"]
    assert ents[1].attributes["occupation"] == "tailor (part-time)"


class DeepPool:
    """Three provider slots answering like DeepClient; `liar` answers as another provider (a failover)."""

    def __init__(self, liar=None):
        self.slots = [SimpleNamespace(provider=p, model=f"{p}-m") for p in ("claude_code", "codex", "antigravity")]
        self.inner = DeepClient()
        self.liar = liar

    def slot_for_provider(self, name):
        from app.utils.model_pool import provider_family
        return next((i for i, s in enumerate(self.slots) if provider_family(s.provider) == provider_family(name)), None)

    def for_slot(self, i):
        slot = self.slots[i % 3]

        def create(**kw):
            resp = self.inner.create(**kw)
            resp._mm_provider = "claude_code" if slot.provider == self.liar else slot.provider
            resp._mm_model = slot.model
            return resp
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                               provider=slot.provider, model_name=slot.model, base_url="")


def test_answers_from_another_provider_are_not_used():
    pool = DeepPool(liar="codex")
    s = pp.PersonaSpec.from_dict({"segments": [seg(count=9)], "seed": 3})
    ents = pp.generate_personas(pool, "m", s, "req", "ctx")
    assert {e.attributes["model_provider"] for e in ents} == {"claude_code", "antigravity"}
    assert len(ents) == 6                                       # codex's 3 are missing, not written by someone else
    assert all(_complete(e) for e in ents)                     # and the others were interviewed by their writers


def test_a_lane_pauses_then_stops_after_failures_in_a_row(monkeypatch):
    from app.services import fast_population as fp
    monkeypatch.setattr(fp, "BREAK_AFTER", 2)
    monkeypatch.setattr(fp, "DEAD_AFTER", 4)
    lane = fp.Lane("codex", 2)
    for _ in range(4):
        lane.acquire()
        lane.release(ok=False)
    import pytest
    with pytest.raises(fp.LaneDown):
        lane.acquire()


def test_the_caller_uses_a_strict_view_of_a_provider_pool():
    from app.services.fast_population import Caller
    from app.utils.model_pool import MultiProviderPool, ProviderSlot
    pool = MultiProviderPool([ProviderSlot(provider="codex", model="m", base_url="u", api_key="k", client=object()),
                              ProviderSlot(provider="claude_code", model="m", base_url="u", api_key="k", client=object())])
    c = Caller(pool, "m", 8)
    assert c.client.strict is True and pool.strict is False
    assert c.family(0) == "codex" and c.family(1) == "claude"

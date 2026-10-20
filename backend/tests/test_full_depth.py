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

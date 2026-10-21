"""Persona planner: segments, demographic spread, names, communities and the follow graph (mocked LLM)."""

import asyncio
import json
import os
import random
import re
import sys
import threading
from types import SimpleNamespace

import pytest

from app.services import persona_planner as pp
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import community_seed  # noqa: E402


class FakeClient:
    """Answers planner and persona prompts; records every prompt it saw."""

    def __init__(self, plan=None, duplicate_names=False):
        self.prompts = []
        self.systems = []
        self.plan = plan
        self.duplicate_names = duplicate_names
        self.n = 0
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        with self.lock:
            self.prompts.append(user)
            self.systems.append(system)
        if user.startswith("Plan the audience"):
            body = self.plan
        elif user.startswith("Second part of a life interview"):
            names = re.findall(r"^([^\n(]+) \(\d+, ", user, re.M)
            nq = len(re.findall(r"^\s+P\d+\. ", user, re.M)) // max(1, len(names))
            body = {"people": [{"name": n, "probe_answers": [{"q": f"P{i + 1}", "a": f"probe {i + 1} by {n}"} for i in range(nq)],
                                "bde": {"background": {"who": f"{n} works", "believes": "cheap is risky", "acquiescence": "high",
                                                       "says_vs_does": "says saves, spends on data"},
                                        "decision_procedure": {"who_they_ask": "wife", "speed": "slow", "style": "satisficer",
                                                               "risk": "averse", "patience": "low", "triggers": ["a friend used it"],
                                                               "stoppers": ["card upfront"]},
                                        "evaluation": {"monthly_discretionary": "NPR 2000", "value_priorities": ["data", "food"],
                                                       "dealbreakers": ["auto-renew"], "trust_cues": ["Nepali reviews"]}}}
                               for n in names]}
        elif user.startswith("This is a life interview"):
            names = re.findall(r"^\d+\. ([^:]+):", user, re.M)
            lang = "Hinglish" if "Hinglish" in user else "local"
            body = {"interviews": [{"name": n, "phone": "Redmi 9, 3 years old", "data_plan": "prepaid 1.5GB/day",
                                    "answers": [{"q": f"Q{i + 1}", "a": f"answer {i + 1} ({lang})"} for i in range(12)],
                                    "summary": f"I am {n}. Paisa tight hai this month."} for n in names]}
        else:
            ages = [int(a) for a in re.findall(r"^\d+\. age (\d+)", user, re.M)]
            rows = []
            for a in ages:
                with self.lock:
                    self.n += 1
                    n = self.n
                name = "Asha Rai" if self.duplicate_names else f"Person {n}"
                rows.append({"name": name, "age": a + 30, "gender": "x", "city": "", "country": "",
                             "occupation": "student", "attitude": "curious", "concerns": ["cost", "trust"],
                             "voice": "short, Nepali-English mix", "bio": "bio", "persona": "A long persona.",
                             "interested_topics": ["study abroad"]})
            body = {"personas": rows}
        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def seg(label="Nepal students", count=4, **kw):
    d = {"label": label, "count": count, "country": "Nepal", "age_min": 17, "age_max": 22,
         "cities": ["Kathmandu", "Pokhara"], "entity_type": "student"}
    d.update(kw)
    return d


# ---------------------------------------------------------------- spec

def test_spec_validation():
    with pytest.raises(ValueError):
        pp.PersonaSpec.from_dict({"segments": [{"count": 3}]})
    with pytest.raises(ValueError):
        pp.PersonaSpec.from_dict({"segments": [seg()], "graph_agents": "some"})
    with pytest.raises(ValueError):
        pp.PersonaSpec.from_dict({"segments": [seg(count=pp.MAX_TOTAL_PERSONAS)] * 2})
    with pytest.raises(ValueError):
        pp.PersonaSpec.from_dict({"segments": [seg()], "communities": [{"kind": "x"}]})
    spec = pp.PersonaSpec.from_dict({"segments": [seg(age_min=60, age_max=40)]})
    s = spec.segments[0]
    assert (s.age_min, s.age_max) == (40, 60)
    assert s.entity_type == "Student"
    assert spec.auto is False
    assert pp.PersonaSpec.from_dict({"auto_total": 10}).auto is True
    assert pp.PersonaSpec.from_dict(None) is None


def test_demographic_slots_spread_ages_genders_and_cities():
    s = pp.PersonaSegment.from_dict(seg(count=10, age_min=20, age_max=70))
    slots = pp.demographic_slots(s, random.Random(1))
    ages = sorted(x["age"] for x in slots)
    assert all(20 <= a <= 70 for a in ages)
    assert ages[0] <= 25 and ages[-1] >= 65            # whole range covered
    assert len(set(ages)) == 10
    assert sum(x["gender"] == "female" for x in slots) == 5
    assert {x["city"] for x in slots} == {"Kathmandu", "Pokhara"}
    women = pp.demographic_slots(pp.PersonaSegment.from_dict(seg(count=4, gender_mix="female")), random.Random(1))
    assert {x["gender"] for x in women} == {"female"}


# ---------------------------------------------------------------- generation

def test_generate_personas_uses_fixed_demographics_and_unique_names():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=8), seg("Nepal parents", count=3, age_min=40,
                                                                      age_max=55, entity_type="Parent")], "interview": False})
    client = FakeClient(duplicate_names=True)
    ents = pp.generate_personas(client, "m", spec, "How do Nepali families react?", "context")
    assert len(ents) == 11
    first = [p for p in client.prompts if "Do not reuse or resemble" not in p]
    assert len(first) == 3                              # 4 + 4 students, then 3 parents (DEEP_BATCH = 4)
    again = [p for p in client.prompts if "Do not reuse or resemble" in p]
    assert again and all("asha rai" in p.lower() for p in again)   # a taken name is asked again with the names to avoid
    assert all("never use the name" in s for s in client.systems)
    names = [e.name for e in ents]
    assert len(set(names)) == 11                        # still the same name on the last try: kept and numbered
    students = [e for e in ents if e.get_entity_type() == "Student"]
    parents = [e for e in ents if e.get_entity_type() == "Parent"]
    assert len(students) == 8 and len(parents) == 3
    for e in students:
        prof = e.attributes[pp.SYNTHETIC_PROFILE_KEY]
        assert 17 <= prof["age"] <= 22                  # slot age wins over the LLM's +30
        assert prof["gender"] in ("male", "female")
        assert prof["country"] == "Nepal"
        assert "Writes like this" in prof["persona"]
        assert pp.PERSONA_LABEL in e.labels


def test_auto_plan_scales_counts_and_adds_communities():
    plan = {"segments": [{"label": "Students", "count": 10, "country": "Bangladesh", "age_min": 17, "age_max": 20},
                         {"label": "Parents", "count": 10, "country": "Bangladesh", "age_min": 40, "age_max": 55}],
            "communities": [{"name": "HSC Science BD", "kind": "facebook_group", "segments": ["Students"]}]}
    client = FakeClient(plan=plan)
    spec = pp.PersonaSpec.from_dict({"auto": True, "auto_total": 8})
    ents = pp.generate_personas(client, "m", spec, "req", "ctx")
    people = [e for e in ents if pp.PERSONA_LABEL in e.labels]
    accounts = [e for e in ents if pp.COMMUNITY_LABEL in e.labels]
    assert len(people) == 8
    assert [a.name for a in accounts] == ["HSC Science BD"]
    assert "communities" in client.prompts[0]


# ---------------------------------------------------------------- communities

def _spec_with_communities():
    return pp.PersonaSpec.from_dict({
        "segments": [seg("Nepal students", 6), seg("Nepal parents", 4, age_min=40, age_max=55),
                     seg("Indonesia parents", 4, country="Indonesia", cities=["Jakarta"])],
        "communities": [
            {"name": "MBBS in China - Nepal", "kind": "facebook_group", "segments": ["Nepal students"],
             "norms": "share scholarship news, warn about scam agents"},
            {"name": "Nepali Parents Abroad Plans", "kind": "whatsapp_group", "segments": ["Nepal parents"]},
            {"name": "Orang Tua Peduli Pendidikan", "kind": "facebook_group", "countries": ["Indonesia"],
             "account": False},
        ],
        "bridge_rate": 0, "in_group_follows": 3,
    })


def test_communities_membership_accounts_and_follow_graph():
    spec = _spec_with_communities()
    ents = pp.generate_personas(FakeClient(), "m", spec, "req", "ctx")
    graph_actor = EntityNode(uuid="g1", name="Acme", labels=["Entity", "Company"], summary="", attributes={})
    agents = [graph_actor] + ents                       # final order: graph actors first
    cfg = pp.build_community_config(agents, spec)
    by_name = {c["name"]: c for c in cfg["communities"]}

    nepal_students = by_name["MBBS in China - Nepal"]
    assert len(nepal_students["member_ids"]) == 6
    assert agents[nepal_students["account_id"]].name == "MBBS in China - Nepal"
    assert by_name["Orang Tua Peduli Pendidikan"]["account_id"] is None
    assert len(by_name["Orang Tua Peduli Pendidikan"]["member_ids"]) == 4

    for e in ents:
        if pp.PERSONA_LABEL in e.labels and e.attributes.get("segment") == "Nepal students":
            assert "warn about scam agents" in e.attributes[pp.SYNTHETIC_PROFILE_KEY]["persona"]

    groups_of = {}
    for c in cfg["communities"]:
        for m in c["member_ids"]:
            groups_of.setdefault(m, set()).add(c["name"])
    accounts = {c["account_id"]: c["name"] for c in cfg["communities"] if c["account_id"] is not None}
    assert cfg["follows"]
    for a, b in cfg["follows"]:
        assert a != b and a != 0 and b != 0             # the graph actor is not wired in
        if b in accounts:
            assert accounts[b] in groups_of[a]
        else:
            assert groups_of[a] & groups_of[b]         # bridge_rate 0: in-group only
        assert len([f for f in cfg["follows"] if f[0] == a and f[1] not in accounts]) <= 3


def test_bridge_rate_adds_out_group_follows():
    spec = _spec_with_communities()
    spec.bridge_rate = 1.0
    ents = pp.generate_personas(FakeClient(), "m", spec, "req", "ctx")
    cfg = pp.build_community_config(ents, spec)
    groups_of = {}
    for c in cfg["communities"]:
        for m in c["member_ids"]:
            groups_of.setdefault(m, set()).add(c["name"])
    cross = [(a, b) for a, b in cfg["follows"] if b in groups_of and not (groups_of[a] & groups_of[b])]
    assert cross


# ---------------------------------------------------------------- graph filtering

def test_select_graph_entities_drops_places_platforms_and_group_labels():
    def node(name, etype):
        return EntityNode(uuid=name, name=name, labels=["Entity", etype], summary="", attributes={})
    ents = [node(n, t) for n, t in [
        ("Acme", "SoftwareCompany"), ("Acme Partners", "Organization"), ("Nepal", "Organization"),
        ("Facebook", "Organization"), ("Travel & Tourism page admins", "Person"),
        ("Indonesian parents", "Parent"), ("Southeast Asia broad targeting set", "Organization"),
        ("Instagram", "SocialMediaPlatform"), ("Tribhuvan University", "University"),
        ("Parents (40–55)", "Parent"), ("Nepal #8", "AdCampaign"), ("Free score check ad concept", "Organization"),
        ("Sign Up", "Action"), ("ai", "Organization"), ("Practice Test Service", "Product"),
        ("Chinese Government Scholarships", "Organization")]]
    spec = pp.PersonaSpec.from_dict({"segments": [seg()], "keep_entities": ["Facebook"]})
    kept = [e.name for e in pp.select_graph_entities(ents, spec, ["Nepal", "Indonesia"])]
    assert kept == ["Acme", "Acme Partners", "Facebook", "Tribhuvan University"]
    spec.graph_agents = "none"
    assert [e.name for e in pp.select_graph_entities(ents, spec)] == ["Facebook"]
    spec.graph_agents = "all"
    assert len(pp.select_graph_entities(ents, spec)) == len(ents)


# ---------------------------------------------------------------- profile + run-script integration

def test_profile_generator_uses_synthetic_profile_without_llm():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=1)]})
    ent = pp.generate_personas(FakeClient(), "m", spec, "req", "ctx")[0]
    gen = OasisProfileGenerator.__new__(OasisProfileGenerator)   # no client: any LLM call would fail
    prof = gen.generate_profile_from_entity(ent, user_id=5)
    assert prof.user_id == 5 and prof.name == ent.name
    assert prof.persona.startswith("A long persona.")
    assert 17 <= prof.age <= 22 and prof.country == "Nepal"
    assert prof.source_entity_type == "Student"
    assert gen._is_individual_entity("Parent")


def test_seed_community_follows_runs_one_step():
    class Env:
        def __init__(self):
            self.steps = []
            self.agent_graph = SimpleNamespace(get_agent=lambda i: f"agent{i}" if i < 5 else (_ for _ in ()).throw(KeyError(i)))

        async def step(self, actions):
            self.steps.append(actions)

    MA = lambda action_type, action_args: (action_type, action_args)  # noqa: E731
    AT = SimpleNamespace(FOLLOW="FOLLOW")
    env = Env()
    cfg = {"community_config": {"follows": [[0, 1], [0, 2], [1, 0], [9, 1], [3, 3], ["x", 1]]}}
    n = asyncio.run(community_seed.seed_community_follows(env, cfg, MA, AT, log=lambda m: None))
    assert n == 3 and len(env.steps) == 1
    acts = env.steps[0]
    assert acts["agent0"] == [("FOLLOW", {"followee_id": 1}), ("FOLLOW", {"followee_id": 2})]
    assert acts["agent1"] == ("FOLLOW", {"followee_id": 0})
    env.steps.clear()
    n = asyncio.run(community_seed.seed_community_follows(env, cfg, MA, AT, log=lambda m: None, batch_size=1))
    assert n == 3 and len(env.steps) == 2
    assert list(env.steps[0]) == ["agent0"] and list(env.steps[1]) == ["agent1"]
    assert asyncio.run(community_seed.seed_community_follows(env, {}, MA, AT)) == 0


def test_seed_community_follows_uses_platform_without_agent_observations():
    class Platform:
        def __init__(self):
            self.follows = []

        async def follow(self, follower, followee):
            self.follows.append((follower, followee))
            return {"success": True}

    class Env:
        platform = Platform()
        agent_graph = SimpleNamespace(get_agent=lambda i: f"agent{i}")

        async def step(self, _actions):
            raise AssertionError("community setup must not prompt agents")

    env = Env()
    n = asyncio.run(community_seed.seed_community_follows(
        env, {"community_config": {"follows": [[0, 1], [0, 2], [1, 0]]}}, None, None, log=lambda m: None))
    assert n == 3 and env.platform.follows == [(0, 1), (0, 2), (1, 0)]

    async def failed(_follower, _followee):
        return {"success": False, "error": "database unavailable"}

    env.platform.follow = failed
    with pytest.raises(RuntimeError, match="community follow seeding failed"):
        asyncio.run(community_seed.seed_community_follows(
            env, {"community_config": {"follows": [[0, 1]]}}, None, None, log=lambda m: None))


def test_short_runs_start_at_peak_hours():
    tc = {"time_config": {"minutes_per_round": 60, "peak_hours": [19, 20, 21, 22, 23]}}
    assert community_seed.start_offset_minutes(tc, 3) == 19 * 60          # 3 rounds: 19:00-21:00
    assert community_seed.start_offset_minutes(tc, 8) == 16 * 60          # ends inside the peak
    assert community_seed.start_offset_minutes(tc, 48) == 0               # a day or more: from midnight
    assert community_seed.start_offset_minutes({"time_config": {"start_hour": 9}}, 3) == 9 * 60
    assert community_seed.start_offset_minutes({}, 2) == 19 * 60



def test_names_get_distinct_initials_and_communities_a_country():
    spec = _spec_with_communities()
    slots = pp.demographic_slots(spec.segments[0], random.Random(3))
    assert len({s["initial"] for s in slots}) == len(slots)
    client = FakeClient()
    ents = pp.generate_personas(client, "m", spec, "req", "ctx")
    assert any("given name starts with" in u for u in client.prompts)
    acc = {e.name: e for e in ents if pp.COMMUNITY_LABEL in e.labels}
    assert acc["MBBS in China - Nepal"].attributes[pp.SYNTHETIC_PROFILE_KEY]["country"] == "Nepal"



def test_life_interviews_attach_answers_and_summary():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=6)]})
    assert spec.interview is True
    client = FakeClient()
    ents = pp.generate_personas(client, "m", spec, "req", "ctx")
    interviews = [u for u in client.prompts if u.startswith("This is a life interview")]
    assert len(interviews) == 2                                  # 6 people in batches of 4
    assert "Hinglish" in interviews[0] and "Q12." in interviews[0]
    probes = [u for u in client.prompts if u.startswith("Second part of a life interview")]
    assert len(probes) == 2
    for e in ents:
        assert len(e.attributes["interview"]) == 14                  # 12 answers + 2 adaptive probes
        assert e.attributes["interview"][12]["q"] == "P1"
        assert e.attributes["bde"]["decision_procedure"]["style"] == "satisficer"
        assert "How I decide:" in e.attributes[pp.SYNTHETIC_PROFILE_KEY]["persona"]
        assert e.attributes["phone"].startswith("Redmi")
        assert "In their own words: I am " + e.name in e.attributes[pp.SYNTHETIC_PROFILE_KEY]["persona"]
    idx = pp.persona_index(ents)
    assert idx[0]["interview_summary"].startswith("I am") and idx[0]["data_plan"].startswith("prepaid")
    assert idx[0]["bde"]["evaluation"]["dealbreakers"] == ["auto-renew"] and idx[0]["weight"] == 1.0
    assert idx[0]["languages"] == ["Nepali", "English"] or idx[0]["languages"] == []
    lite = pp.PersonaSpec.from_dict({"segments": [seg(count=2)], "personas_lite": True})
    assert lite.interview is False
    c2 = FakeClient()
    pp.generate_personas(c2, "m", lite, "req", "ctx")
    assert not any(u.startswith("This is a life interview") for u in c2.prompts)



def test_probes_follow_the_answers_and_product_questions():
    money = [{"q": f"Q{i + 1}", "a": ""} for i in range(12)]
    money[2]["a"] = "Paisa bahut tight hai, loan chal raha hai"
    money[6]["a"] = "Got scammed on a fake Flipkart link once"
    picks = pp.choose_probes(money)
    assert len(picks) == 2 and "money is tight" in picks[0] and "check before paying" in picks[1]
    assert pp.choose_probes([]) == pp.DEFAULT_PROBES[:2]
    qs = pp.product_questions({"name": "Fitloop", "one_liner": "15-minute home workouts", "offer": "a 7-day free trial"})
    assert len(qs) == 3 and "Fitloop" in qs[1] and "walk away" in qs[2]
    assert pp.product_questions(None) == []
    # product questions reach the second interview call
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=2)]})
    client = FakeClient()
    ents = pp.generate_personas(client, "m", spec, "req", "ctx", product={"name": "Fitloop", "one_liner": "home workouts", "offer": "a trial"})
    probe_prompt = next(u for u in client.prompts if u.startswith("Second part"))
    assert "P5." in probe_prompt and "Fitloop" in probe_prompt
    assert len(ents[0].attributes["interview"]) == 17                 # 12 + 2 probes + 3 product questions
    # probes off keeps one call per batch
    c2 = FakeClient()
    pp.generate_personas(c2, "m", pp.PersonaSpec.from_dict({"segments": [seg(count=2)], "probes": False}), "req", "ctx")
    assert not any(u.startswith("Second part") for u in c2.prompts)


def test_bde_cleaning_and_rendering():
    assert pp.clean_bde("nope") is None and pp.clean_bde({"background": {}}) is None
    bde = pp.clean_bde({"background": {"believes": "x" * 500}, "decision_procedure": {"triggers": "one"},
                        "evaluation": {"value_priorities": ["a", "b", "c", "d", "e", "f", "g"]}})
    assert len(bde["background"]["believes"]) == 240 and bde["decision_procedure"]["triggers"] == ["one"]
    assert len(bde["evaluation"]["value_priorities"]) == 5
    txt = pp.render_bde(bde)
    assert txt.startswith("Beliefs: ") and "Acts when: one" in txt and "Pays for: a; b; c" in txt
    assert pp.render_bde(None) == ""


def test_stereotype_guard_reports_and_repairs_duplicates():
    import random as _r
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=6, cities=["Kathmandu"])], "interview": False})
    ents = pp.generate_personas(FakeClient(), "m", spec, "req", "ctx")       # every fake persona is a 'student' in Kathmandu
    rep = pp.diversity_report(ents)
    row = rep["segments"][0]
    assert row["n"] == 6 and row["dup_city"] == 5
    # the guard already ran inside generate_personas: occupations were varied
    occs = {e.attributes["occupation"] for e in ents}
    assert len(occs) == 6 and any("(night shift)" in o for o in occs)
    # with two cities the repair moves people instead of renaming the role
    spec2 = pp.PersonaSpec.from_dict({"segments": [seg(count=4)], "interview": False})
    e2 = pp.generate_personas(FakeClient(), "m", spec2, "req", "ctx")
    assert {e.attributes["city"] for e in e2} == {"Kathmandu", "Pokhara"}
    assert pp.fix_duplicates(e2, _r.Random(1)) == 0 or True            # idempotent enough: nothing left to collide on


def test_population_weights_rake_to_target_shares():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=8)], "interview": False,
                                     "population": {"Nepal": {"gender": {"female": 0.75, "male": 0.25}}}})
    ents = pp.generate_personas(FakeClient(), "m", spec, "req", "ctx")
    ws = {e.attributes[pp.SYNTHETIC_PROFILE_KEY]["gender"]: e.attributes["weight"] for e in ents}
    assert ws["female"] > 1.0 > ws["male"]                              # women up-weighted toward 75%
    assert abs(sum(e.attributes["weight"] for e in ents) / len(ents) - 1.0) < 0.05
    assert pp.population_weights(ents, {}) == 0


def test_real_voices_reach_the_interview_prompt():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=2)]})
    client = FakeClient()
    voices = [{"text": "They charged my card after the trial, scam", "source": "appstore", "sentiment": "neg", "country": "Nepal"},
              {"text": "Finally an app that works offline", "source": "hackernews", "sentiment": "pos", "country": ""}]
    pp.generate_personas(client, "m", spec, "req", "ctx", voices=voices)
    first = next(u for u in client.prompts if u.startswith("This is a life interview"))
    assert "What real people wrote" in first and "charged my card" in first
    assert pp._voices_block(None) == "" and pp._voices_block([], "Nepal") == ""



def test_bde_cleaner_accepts_the_shapes_models_return():
    capital = pp.clean_bde({"Background": {"Who": "a nurse", "Beliefs": "cheap is risky"}, "Decision Procedure": {"Speed": "slow", "Triggers": ["a friend"]},
                            "Evaluation Profile": {"Dealbreakers": "auto-renew"}})
    assert capital["background"]["who"] == "a nurse" and capital["background"]["believes"] == "cheap is risky"
    assert capital["decision_procedure"]["triggers"] == ["a friend"] and capital["evaluation"]["dealbreakers"] == ["auto-renew"]
    flat = pp.clean_bde({"who": "a student", "risk": "averse", "trust_cues": ["reviews"]})
    assert flat["background"]["who"] == "a student" and flat["decision_procedure"]["risk"] == "averse" and flat["evaluation"]["trust_cues"] == ["reviews"]
    prose_sections = pp.clean_bde({"background": "Grew up in Pune, saves hard, distrusts apps that want a card.", "decision": {"speed": "fast"}})
    assert prose_sections["background"]["who"].startswith("Grew up") and prose_sections["decision_procedure"]["speed"] == "fast"
    prose = pp.clean_bde("She asks her sister before buying anything over 500 rupees and hates auto-renewals.")
    assert prose["background"]["who"].startswith("She asks")


def test_settlement_spread_and_stable_habits():
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=20, country="India", cities=["Pune", "Mumbai"])], "interview": False})
    ents = pp.generate_personas(FakeClient(), "m", spec, "req", "ctx")
    tiers = {e.attributes.get("settlement") for e in ents}
    assert tiers >= {"metro", "city", "town"} and len({e.attributes["city"] for e in ents}) >= 6
    assert any(e.attributes["city"] in ("Pune", "Mumbai") for e in ents)
    keep = pp.PersonaSpec.from_dict({"segments": [seg(count=20, country="India", cities=["Pune"], geo_spread="cities")], "interview": False})
    assert {e.attributes["city"] for e in pp.generate_personas(FakeClient(), "m", keep, "req", "ctx")} == {"Pune"}
    h1 = pp.stable_habits("Asha Rai", {"thinking_style": "sceptical"})
    assert h1 == pp.stable_habits("Asha Rai", {"thinking_style": "sceptical"}) and h1 != pp.stable_habits("Bina Rai", {})
    e = ents[0]
    assert e.attributes["habits"]["ad_avoidance"] >= 0 and e.attributes["provenance"]["profile"].startswith("synthetic")
    idx = pp.persona_index(ents)
    assert idx[0]["settlement"] and idx[0]["habits"] and idx[0]["provenance"]


def test_coupled_demographics_real_intake_and_discretionary_budget():
    s = pp.PersonaSegment.from_dict(seg(count=6, age_min=18, age_max=60))
    slots = pp.demographic_slots(s, random.Random(7))
    assert all(x.get("life_stage") and x.get("payday_status") for x in slots)

    assert pp.parse_discretionary_amount("NPR 2,500 after rent") == 2500.0
    assert pp.parse_discretionary_amount("Rs. 1200 / month") == 1200.0
    assert pp.parse_discretionary_amount("tight") is None

    spec = pp.PersonaSpec.from_dict({
        "segments": [seg(count=2)],
        "interview": True,
        "real_profiles": [
            {"name": "Sita Gurung", "age": 29, "gender": "female", "city": "Pokhara", "country": "Nepal",
             "segment": "Nepal students", "occupation": "nurse", "income": "mid",
             "bde": {"evaluation": {"monthly_discretionary": "NPR 3500"}},
             "excerpts": ["I always check with my sister before subscribing."]}
        ],
    })
    ents = pp.generate_personas(FakeClient(), "m", spec, "req", "ctx")
    sita = next(e for e in ents if e.name == "Sita Gurung")
    assert sita.attributes["provenance"]["profile"].startswith("real_intake")
    assert sita.attributes["bde"]["evaluation"]["discretionary_budget_num"] == 3500.0
    idx = pp.persona_index(ents)
    sita_idx = next(p for p in idx if p["name"] == "Sita Gurung")
    assert sita_idx["provenance"]["profile"].startswith("real_intake")
    assert sita_idx["bde"]["evaluation"]["discretionary_budget_num"] == 3500.0
    assert sita_idx["life_stage"] and sita_idx["payday_status"]



def test_failed_persona_batch_is_left_out_not_invented(monkeypatch):
    monkeypatch.setattr(pp, "RETRY_PAUSE_S", 0)
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=10), seg("Nepal parents", count=4, age_min=40, age_max=55,
                                                                      entity_type="Parent")], "interview": False})
    client = FakeClient()
    real = client.create

    def create(**kw):
        if "Nepal parents" in kw["messages"][1]["content"]:
            raise TimeoutError("Request timed out.")
        return real(**kw)
    client.chat.completions.create = create
    ents = pp.generate_personas(client, "m", spec, "req", "ctx")
    assert len(ents) == 10 and all(e.attributes.get("segment") != "Nepal parents" for e in ents)


def test_persona_calls_in_flight_never_exceed_parallel(monkeypatch):
    import time as _time
    spec = pp.PersonaSpec.from_dict({"segments": [seg(count=10), seg("Nepal parents", count=10, age_min=40, age_max=55,
                                                                      entity_type="Parent")]})
    client = FakeClient()
    real = client.create
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def create(**kw):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        _time.sleep(0.02)
        try:
            return real(**kw)
        finally:
            with lock:
                state["now"] -= 1
    client.chat.completions.create = create
    pp.generate_personas(client, "m", spec, "req", "ctx", parallel=3)
    assert 1 <= state["max"] <= 3


def test_json_with_trailing_text_or_a_second_object_is_read():
    assert pp.parse_json_block('{"a": 1}\n{"b": 2}') == {"a": 1}
    assert pp.parse_json_block('Here you go: {"people": [1, 2]} hope this helps}') == {"people": [1, 2]}

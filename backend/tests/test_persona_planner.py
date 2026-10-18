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
        pp.PersonaSpec.from_dict({"segments": [seg(count=500)] * 5})
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
                                                                      age_max=55, entity_type="Parent")]})
    client = FakeClient(duplicate_names=True)
    ents = pp.generate_personas(client, "m", spec, "How do Nepali families react?", "context")
    assert len(ents) == 11
    assert len(client.prompts) == 2                     # 8 in one call, then 3
    assert all("never use the name" in s for s in client.systems)
    names = [e.name for e in ents]
    assert len(set(names)) == 11                        # duplicates from the LLM are renamed
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
    assert asyncio.run(community_seed.seed_community_follows(env, {}, MA, AT)) == 0


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

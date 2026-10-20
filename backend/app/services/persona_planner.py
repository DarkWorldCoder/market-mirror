"""
Persona planner: synthetic, demographically grounded individual agents and the
communities they gather in.

The knowledge graph alone tends to turn countries, platforms and campaigns into
"agents" and yields very few real people. The planner adds concrete individuals
for each audience segment the user describes (or that Claude infers from the
simulation requirement): a fixed count per segment, ages spread evenly across
the segment's range, a balanced gender mix, rotating cities, and realistic
local names.

Communities (Facebook groups, WhatsApp chats, subreddits, clubs...) split people
the way real life does. Each persona joins up to N matching communities and
inherits their norms, each community can get an admin/page account, and an
in-group follow graph is seeded before round 1 so feeds are mostly in-group,
with a small cross-group bridge rate.

Names are invented and culturally plausible for the segment's country. The
prompt forbids real or public people; personas are never built from real
individuals' data.

Each persona becomes an EntityNode whose attributes carry a ready profile under
SYNTHETIC_PROFILE_KEY, so the normal profile and config pipeline treats it like
any other agent without a second LLM call.
"""

from __future__ import annotations

import os
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..utils.logger import get_logger
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from .zep_entity_reader import EntityNode

logger = get_logger('mirofish.persona_planner')

SYNTHETIC_PROFILE_KEY = "_synthetic_profile"
PERSONA_LABEL = "SyntheticPersona"
COMMUNITY_LABEL = "SyntheticCommunity"
RETRY_PAUSE_S = float(os.environ.get("PERSONA_RETRY_PAUSE_S") or 3)
# depth "auto" (opt-in) switches to cards plus an interviewed sample above this many people (MM_FAST_ABOVE)
FAST_ABOVE = max(0, int(os.environ.get("MM_FAST_ABOVE") or 300))
MAX_PER_CALL = 5                 # shorter calls: a retry costs less and segments finish sooner
# a guard against typos, not a model limit; raise it with MM_MAX_PERSONAS for larger markets
MAX_TOTAL_PERSONAS = max(1, int(os.environ.get("MM_MAX_PERSONAS") or 5000))
# Traits spread evenly across each segment (like ages and genders) so personas do not collapse
# toward one "typical" respondent. Override per spec ("diversity") or per segment.
DEFAULT_DIVERSITY: Dict[str, List[str]] = {
    "upbringing": ["big-city", "small town", "rural village", "suburban", "migrant or diaspora family",
                   "moved from village to city"],
    "education": ["secondary school or less", "vocational or diploma", "some university", "bachelor's degree",
                  "postgraduate degree"],
    "income": ["low", "lower-middle", "middle", "upper-middle", "high"],
    "thinking_style": ["analytical, wants evidence", "intuitive, goes with gut feeling", "sceptical, expects a catch",
                       "early adopter, loves trying new things", "traditional, trusts family and elders",
                       "price-hunter, compares everything", "risk-averse, avoids commitments",
                       "status-driven, cares what others think", "busy and distracted, skims everything"],
    "tech_comfort": ["low", "medium", "high"],
    "media_diet": ["mostly short video", "mostly Facebook groups and family chats", "news sites and YouTube",
                   "Reddit and forums", "Instagram and creators", "barely uses social media"],
}
MBTI = ["INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP"]


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------

def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def _type_name(v: Any) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(v))
    return "".join(w[:1].upper() + w[1:] for w in words) or "Person"


@dataclass
class PersonaSegment:
    label: str
    count: int = 5
    country: str = ""
    cities: List[str] = field(default_factory=list)
    age_min: int = 18
    age_max: int = 65
    role: str = ""
    entity_type: str = "Person"
    languages: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    gender_mix: str = "balanced"          # balanced | female | male | share of women 0-1
    notes: str = ""                        # real data, attitudes, what is known about this group
    diversity: Dict[str, List[str]] = field(default_factory=dict)   # per-segment trait overrides
    geo_spread: str = "auto"               # auto | national | cities (see geo_tiers.spread)
    settlement_mix: Dict[str, float] = field(default_factory=dict)  # {"metro": .45, "city": .3, "town": .15, "rural": .1}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PersonaSegment":
        if not isinstance(d, dict) or not str(d.get("label") or "").strip():
            raise ValueError("each persona segment needs a non-empty 'label'")
        age_min, age_max = _int(d.get("age_min"), 18), _int(d.get("age_max"), 65)
        if age_min > age_max:
            age_min, age_max = age_max, age_min
        return cls(
            label=str(d["label"]).strip(),
            count=max(1, min(_int(d.get("count"), 5), MAX_TOTAL_PERSONAS)),
            country=str(d.get("country") or "").strip(),
            cities=_str_list(d.get("cities")),
            age_min=max(10, age_min),
            age_max=min(100, age_max),
            role=str(d.get("role") or "").strip(),
            entity_type=_type_name(d.get("entity_type") or "Person"),
            languages=_str_list(d.get("languages")),
            platforms=_str_list(d.get("platforms")),
            gender_mix=str(d.get("gender_mix") or "balanced").strip().lower(),
            notes=str(d.get("notes") or "").strip(),
            diversity=_diversity(d.get("diversity")),
            geo_spread=str(d.get("geo_spread") or "auto").strip().lower(),
            settlement_mix={str(k): float(v) for k, v in (d.get("settlement_mix") or {}).items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool)} if isinstance(d.get("settlement_mix"), dict) else {},
        )


def _diversity(v: Any) -> Dict[str, List[str]]:
    if not isinstance(v, dict):
        return {}
    return {str(k): _str_list(vals) for k, vals in v.items() if _str_list(vals)}


@dataclass
class CommunitySpec:
    name: str
    kind: str = "online group"            # facebook_group | whatsapp_group | subreddit | forum | local_club ...
    description: str = ""
    norms: str = ""                        # tone, rules, what gets shared, how members treat ads/outsiders
    segments: List[str] = field(default_factory=list)    # segment labels whose members join
    countries: List[str] = field(default_factory=list)   # or: anyone from these countries may join
    join_share: float = 1.0                # share of matching personas who join
    account: bool = True                   # add an admin/page account that posts for the group

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CommunitySpec":
        if not isinstance(d, dict) or not str(d.get("name") or "").strip():
            raise ValueError("each community needs a non-empty 'name'")
        return cls(
            name=str(d["name"]).strip(),
            kind=str(d.get("kind") or "online group").strip(),
            description=str(d.get("description") or "").strip(),
            norms=str(d.get("norms") or "").strip(),
            segments=_str_list(d.get("segments")),
            countries=_str_list(d.get("countries")),
            join_share=max(0.0, min(1.0, _float(d.get("join_share", 1.0), 1.0))),
            account=bool(d.get("account", True)),
        )


@dataclass
class PersonaSpec:
    segments: List[PersonaSegment] = field(default_factory=list)
    communities: List[CommunitySpec] = field(default_factory=list)
    auto: bool = False                 # let the LLM plan segments (and communities) from the requirement
    auto_total: int = 24               # personas to aim for in auto mode
    auto_communities: bool = True      # in auto mode, also plan communities when none are given
    max_communities_per_person: int = 2
    in_group_follows: int = 6          # each member follows up to this many fellow members
    bridge_rate: float = 0.05          # chance of also following someone outside one's communities
    graph_agents: str = "auto"         # all | none | auto (drop places/platforms/campaigns/group labels)
    keep_entities: List[str] = field(default_factory=list)   # graph entity names to always keep
    diversity: Dict[str, List[str]] = field(default_factory=dict)   # trait overrides for every segment
    interview: bool = True             # life interview per person (research: interview-grounded personas predict better)
    probes: bool = True                # second interview call: adaptive follow-ups, product questions, BDE card
    population: Dict[str, Any] = field(default_factory=dict)   # {country: {"age": {...}, "gender": {...}}} target shares
    real_profiles: List[Dict[str, Any]] = field(default_factory=list)  # grounded customer excerpts/records with provenance
    seed: int = 7
    depth: str = "full"                # full: every person interviewed | fast: cards + an interviewed sample | auto
    interview_share: float = 0.1       # fast depth: share of each segment x provider given the full interview

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> Optional["PersonaSpec"]:
        if not d:
            return None
        if not isinstance(d, dict):
            raise ValueError("persona_spec must be a JSON object")
        mode = str(d.get("graph_agents") or "auto").lower()
        if mode not in ("all", "none", "auto"):
            raise ValueError("persona_spec.graph_agents must be all, none or auto")
        segs = [PersonaSegment.from_dict(s) for s in (d.get("segments") or [])]
        real_raw = [r for r in (d.get("real_profiles") or []) if isinstance(r, dict)]
        spec = cls(
            segments=segs,
            communities=[CommunitySpec.from_dict(c) for c in (d.get("communities") or [])],
            auto=bool(d.get("auto", not segs and not real_raw)),
            auto_total=max(4, min(_int(d.get("auto_total"), 24), MAX_TOTAL_PERSONAS)),
            auto_communities=bool(d.get("auto_communities", True)),
            max_communities_per_person=max(1, min(_int(d.get("max_communities_per_person"), 2), 5)),
            in_group_follows=max(0, min(_int(d.get("in_group_follows"), 6), 50)),
            bridge_rate=max(0.0, min(1.0, _float(d.get("bridge_rate", 0.05), 0.05))),
            graph_agents=mode,
            keep_entities=_str_list(d.get("keep_entities")),
            diversity=_diversity(d.get("diversity")),
            interview=bool(d.get("interview", True)) and not bool(d.get("personas_lite", False)),
            probes=bool(d.get("probes", True)) and not bool(d.get("personas_lite", False)),
            population=dict(d.get("population") or {}) if isinstance(d.get("population"), dict) else {},
            real_profiles=real_raw,
            seed=_int(d.get("seed"), 7),
            depth=str(d.get("depth") or "full").lower(),
            interview_share=max(0.0, min(1.0, _float(d.get("interview_share", 0.1), 0.1))),
        )
        if spec.depth not in ("auto", "full", "fast"):
            raise ValueError("persona_spec.depth must be auto, full or fast")
        total = sum(s.count for s in spec.segments)
        if total > MAX_TOTAL_PERSONAS:
            raise ValueError(f"persona_spec asks for {total} personas; the limit is {MAX_TOTAL_PERSONAS}")
        return spec

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Deterministic demographic slots
# --------------------------------------------------------------------------

def _female_share(mix: str) -> float:
    if mix in ("female", "women", "f"):
        return 1.0
    if mix in ("male", "men", "m"):
        return 0.0
    if mix in ("balanced", "", "mixed"):
        return 0.5
    return max(0.0, min(1.0, _float(mix, 0.5)))


def _life_stage(age: int) -> str:
    if age <= 21:
        return "student / early youth"
    if age <= 28:
        return "young adult / early career"
    if age <= 42:
        return "established adult / family builder"
    if age <= 57:
        return "mid-life household head"
    return "older adult / senior"


def _couple_slot_traits(
    age: int,
    settlement: str,
    raw_traits: Dict[str, str],
    allowed_traits: Dict[str, List[str]],
    rng: random.Random,
) -> Dict[str, str]:
    """Enforce realistic conditional coupling between age, settlement tier, education, income, and tech comfort."""
    out = dict(raw_traits)
    edu = out.get("education", "")
    allowed_edu = allowed_traits.get("education") or DEFAULT_DIVERSITY["education"]
    if age < 20 and edu in ("postgraduate degree", "bachelor's degree"):
        candidates = [e for e in allowed_edu if e in ("secondary school or less", "some university", "vocational or diploma")]
        if candidates:
            out["education"] = rng.choice(candidates)
    elif 20 <= age < 22 and edu == "postgraduate degree":
        candidates = [e for e in allowed_edu if e != "postgraduate degree"]
        if candidates:
            out["education"] = rng.choice(candidates)

    inc = out.get("income", "")
    allowed_inc = allowed_traits.get("income") or DEFAULT_DIVERSITY["income"]
    if age <= 21 and inc in ("high", "upper-middle"):
        candidates = [x for x in allowed_inc if x in ("low", "lower-middle", "middle")]
        if candidates:
            out["income"] = rng.choice(candidates)
    elif settlement == "rural" and inc == "high" and rng.random() < 0.75:
        candidates = [x for x in allowed_inc if x in ("low", "lower-middle", "middle")]
        if candidates:
            out["income"] = rng.choice(candidates)

    if settlement == "rural" and out.get("upbringing") == "big-city":
        allowed_up = allowed_traits.get("upbringing") or DEFAULT_DIVERSITY["upbringing"]
        candidates = [x for x in allowed_up if x in ("rural village", "small town")]
        if candidates:
            out["upbringing"] = rng.choice(candidates)

    if age >= 58 and out.get("tech_comfort") == "high" and rng.random() < 0.65:
        allowed_tc = allowed_traits.get("tech_comfort") or DEFAULT_DIVERSITY["tech_comfort"]
        candidates = [x for x in allowed_tc if x in ("low", "medium")]
        if candidates:
            out["tech_comfort"] = rng.choice(candidates)

    return out


PAYDAY_STATES = ("just_paid", "mid_month", "end_of_month_tight")


def demographic_slots(seg: PersonaSegment, rng: random.Random,
                      diversity: Optional[Dict[str, List[str]]] = None) -> List[Dict[str, Any]]:
    """Ages spread evenly over [age_min, age_max], genders by gender_mix, cities round-robin,
    and diversity traits spread across the segment with realistic life-stage/demographic coupling."""
    n = seg.count
    span = seg.age_max - seg.age_min
    ages = [seg.age_min + round(span * (i + 0.5) / n) for i in range(n)]
    women = round(n * _female_share(seg.gender_mix))
    genders = ["female"] * women + ["male"] * (n - women)
    rng.shuffle(genders)
    rng.shuffle(ages)
    from .geo_tiers import spread as _spread_places
    places = _spread_places(seg.country, seg.cities, n, rng, seg.geo_spread, seg.settlement_mix or None)
    traits = {**DEFAULT_DIVERSITY, **(diversity or {}), **seg.diversity}
    spread: Dict[str, List[str]] = {}
    for name, values in traits.items():
        vals = list(values)
        cycle = (vals * (n // len(vals) + 1))[:n] if vals else []
        rng.shuffle(cycle)
        spread[name] = cycle
    # distinct starting letters for given names: parallel batches otherwise all pick the most common names
    letters = list("ABCDEFGHIJKLMNOPRSTVY")
    rng.shuffle(letters)
    paydays = [PAYDAY_STATES[i % len(PAYDAY_STATES)] for i in range(n)]
    rng.shuffle(paydays)
    slots: List[Dict[str, Any]] = []
    for i in range(n):
        age = ages[i]
        city, settlement = places[i][0], places[i][1]
        raw_t = {k: v[i] for k, v in spread.items() if v}
        coupled_t = _couple_slot_traits(age, settlement, raw_t, traits, rng)
        slots.append({
            "age": age,
            "gender": genders[i],
            "city": city,
            "settlement": settlement,
            "life_stage": _life_stage(age),
            "payday_status": paydays[i],
            "mbti": rng.choice(MBTI),
            "initial": letters[i % len(letters)],
            "traits": coupled_t,
        })
    return slots


# --------------------------------------------------------------------------
# Graph entity filtering
# --------------------------------------------------------------------------

_ABSTRACT_TYPES = {
    "location", "country", "region", "city", "place", "geography", "market", "platform",
    "socialmediaplatform", "socialmedia", "website", "app", "product", "campaign", "adset",
    "advertisement", "ad", "event", "topic", "concept", "policy", "document", "page",
    "objection", "benefit", "pricepoint", "price", "channel", "offer",   # market-map nodes from the ontology
}
_ABSTRACT_NAME = re.compile(
    r"\b(targeting|ad ?sets?|campaigns?|interest category|page admins?|guide page|landing page|"
    r"segment [a-z0-9]|segments?|audience|broad|set [a-z])\b", re.I)
_PEOPLE_GROUP = re.compile(r"\b(students?|parents?|users?|customers?|people|families|voters?|residents?|"
                           r"teachers?|employees?|consumers?|citizens?|youth|adults?|seniors?)\b", re.I)
_PLATFORMS = {"facebook", "instagram", "meta", "tiktok", "youtube", "twitter", "x", "reddit", "whatsapp",
              "messenger", "threads", "linkedin", "google", "snapchat", "telegram", "wechat", "line"}


_NOT_ACTOR_TYPE = ("campaign", "adset", "advert", "platform", "product", "service", "concept", "event", "test",
                   "exam", "program", "offer", "feature", "page", "topic", "policy", "document", "location", "country",
                   "region", "city", "market", "segment", "audience", "metric", "action", "message", "creative")
_NOT_ACTOR_NAME = re.compile(
    r"#\d|\bconcepts?\b|\bsign[- ]?ups?\b|\btests?\b|\bads?\b|\bservices?\b|\bprograms?\b|\bscholarships?\b|"
    r"\bchallenge\b|\bguide\b|\bexplainer\b|\bcheck\b|\bofferings?\b", re.I)


def is_abstract_entity(entity: EntityNode, countries: Sequence[str] = ()) -> bool:
    """True for graph entities that should not speak as agents once synthetic personas exist:
    places, platforms, campaigns, products, concepts and generic audience labels."""
    etype = (entity.get_entity_type() or "").lower()
    name = (entity.name or "").strip()
    low = name.lower()
    if etype in _ABSTRACT_TYPES or any(t in etype for t in _NOT_ACTOR_TYPE) or low in _PLATFORMS:
        return True
    if low in {c.lower() for c in countries if c}:
        return True
    if _ABSTRACT_NAME.search(name) or _NOT_ACTOR_NAME.search(name):
        return True
    if len(re.sub(r"[^a-z0-9]", "", low)) <= 3:          # fragments like "ai", "SCA"
        return True
    # "Indonesian parents", "Students", "Parents (40-55)": generic groups the personas replace
    if _PEOPLE_GROUP.search(name) and len(re.findall(r"[A-Za-z]+", name)) <= 4:
        return True
    return False


def select_graph_entities(entities: List[EntityNode], spec: PersonaSpec,
                          countries: Sequence[str] = ()) -> List[EntityNode]:
    keep = {k.lower() for k in spec.keep_entities}
    if spec.graph_agents == "all":
        return list(entities)
    if spec.graph_agents == "none":
        return [e for e in entities if e.name.lower() in keep]
    return [e for e in entities if e.name.lower() in keep or not is_abstract_entity(e, countries)]


def spec_countries(spec: PersonaSpec) -> List[str]:
    out = {s.country for s in spec.segments if s.country}
    for c in spec.communities:
        out.update(c.countries)
    return sorted(out)


# --------------------------------------------------------------------------
# LLM calls
# --------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You design realistic synthetic personas for social simulation research. Every person you write is "
    "fictional: invent names that are common and culturally plausible for the given country and age, and "
    "never use the name, likeness or biography of a real or public person. Ground attitudes in the context "
    "and notes provided, include disagreement and indifference as well as enthusiasm, and avoid stereotypes "
    "beyond what the notes support. Return only valid JSON."
)


def _resolve_provider_meta(client: Any, model: str, resp: Any = None, slot_index: Optional[int] = None) -> Tuple[str, str]:
    from ..utils.model_pool import canonical_provider
    prov = getattr(resp, "_mm_provider", None) if resp is not None else None
    mod = getattr(resp, "_mm_model", None) if resp is not None else None
    if not prov and slot_index is not None and hasattr(client, "for_slot"):
        bound = client.for_slot(slot_index)
        prov = getattr(bound, "provider", None)
        mod = mod or getattr(bound, "model_name", None)
    if not prov:
        prov = getattr(client, "provider", None) or canonical_provider(None, str(getattr(client, "base_url", "") or ""), model)
    return str(prov or "claude"), str(mod or model or "default")


def _llm_json(
    client,
    model: str,
    prompt: str,
    temperature: float = 0.8,
    max_tokens: int = 8000,
    slot_index: Optional[int] = None,
    return_meta: bool = False,
    gate: Optional[threading.Semaphore] = None,
) -> Any:
    """One persona-planner call, retried twice with a short pause. `gate` caps how many calls run at once across
    writing and interviews, so login gateways are not sent more than they can answer before timing out."""
    last: Optional[Exception] = None
    for attempt in range(3):
        if attempt:
            time.sleep(RETRY_PAUSE_S * attempt)
        try:
            call_kw: Dict[str, Any] = {
                "model": model,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                "temperature": max(0.2, temperature - 0.2 * attempt),
                "max_tokens": max_tokens,
            }
            if slot_index is not None:
                call_kw["slot_index"] = slot_index
            if gate is not None:
                with gate:
                    resp = create_chat_completion(client, **call_kw)
            else:
                resp = create_chat_completion(client, **call_kw)
            parsed = parse_json_block(extract_chat_completion_text(resp))
            if return_meta:
                prov, mod = _resolve_provider_meta(client, model, resp, slot_index)
                return parsed, prov, mod
            return parsed
        except Exception as e:  # noqa: BLE001 - retried, then surfaced
            last = e
            logger.warning(f"persona LLM call failed (attempt {attempt + 1}): {str(e)[:120]}")
    raise RuntimeError(f"persona generation failed: {last}")


def parse_json_block(text: str) -> Any:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
        if not starts:
            raise
        start = min(starts)
        try:                                     # the first complete value, even with text or a second one after it
            return json.JSONDecoder().raw_decode(text[start:])[0]
        except ValueError:
            end = max(text.rfind("}"), text.rfind("]"))
            return json.loads(text[start:end + 1])


_SEGMENT_SCHEMA = (
    '{"label": "...", "count": N, "country": "...", "cities": ["..."], "age_min": N, "age_max": N, '
    '"role": "...", "entity_type": "Student|Parent|Customer|Voter|Person|...", "languages": ["..."], '
    '"platforms": ["..."], "gender_mix": "balanced", "notes": "what is known about this group from the '
    'context, including any real results"}'
)
_COMMUNITY_SCHEMA = (
    '{"name": "realistic group name", "kind": "facebook_group|whatsapp_group|subreddit|forum|'
    'instagram_community|local_club|...", "description": "...", "norms": "tone, rules, what members share '
    'and how they treat ads and outsiders", "segments": ["segment labels whose members join"], '
    '"countries": ["..."], "join_share": 0.8, "account": true}'
)


def plan_segments(client, model: str, requirement: str, context: str, total: int,
                  with_communities: bool = True) -> Tuple[List[PersonaSegment], List[CommunitySpec]]:
    """Ask the LLM to split the audience into segments and the communities they gather in."""
    communities_part = ""
    schema = '{"segments": [' + _SEGMENT_SCHEMA + ']}'
    if with_communities:
        communities_part = (
            "\nAlso propose 2-8 communities where these people actually gather (groups, chats, forums, clubs). "
            "Communities should separate people the way real life does (by country, language, role, age, "
            "interest), and some people should belong to two.\n")
        schema = '{"segments": [' + _SEGMENT_SCHEMA + '], "communities": [' + _COMMUNITY_SCHEMA + ']}'
    prompt = (
        "Plan the audience for a social media simulation.\n\n"
        f"Simulation requirement:\n{requirement[:4000]}\n\n"
        f"Background (excerpt of the seed documents):\n{context[:6000]}\n\n"
        "Split the people who should be simulated into 3-8 segments that together cover every audience, "
        "country and age group the requirement mentions (for example students and parents, younger and older "
        "adults, each country separately). Include sceptics and bystanders where realistic. "
        f"Aim for about {total} people in total.\n{communities_part}\nReturn JSON: {schema}"
    )
    data = _llm_json(client, model, prompt, temperature=0.4, max_tokens=5000)
    raw = data.get("segments") if isinstance(data, dict) else data
    segs = [PersonaSegment.from_dict(s) for s in (raw or []) if isinstance(s, dict) and s.get("label")]
    if not segs:
        raise RuntimeError("the persona planner returned no segments")
    have = sum(s.count for s in segs)
    if have and have != total:
        for s in segs:
            s.count = max(1, round(s.count * total / have))
    comms: List[CommunitySpec] = []
    if with_communities and isinstance(data, dict):
        comms = [CommunitySpec.from_dict(c) for c in (data.get("communities") or [])
                 if isinstance(c, dict) and c.get("name")]
    return segs, comms


def _persona_prompt(seg: PersonaSegment, slots: List[Dict[str, Any]], requirement: str, context: str,
                    avoid_names: Sequence[str] = (), communities: Sequence[CommunitySpec] = (),
                    numbers: Optional[Sequence[int]] = None) -> str:
    """The full-depth persona request. Each row carries its slot number ("i") so a broken or short answer keeps its
    good rows and only the missing people are asked again; the fixed demographics are not written back."""
    numbers = list(numbers) if numbers else list(range(1, len(slots) + 1))
    people = "\n".join(
        f"{n}. age {s['age']}, {s['gender']}" + (f", lives in {s['city']}" if s["city"] else "")
        + ({"metro": " (big metro)", "city": " (mid-sized city)", "town": " (small town)", "rural": " (rural, village life)"}.get(s.get("settlement") or "", ""))
        + f", MBTI {s['mbti']}" + (f", given name starts with '{s['initial']}'" if s.get("initial") else "")
        + "".join(f"; {k.replace('_', ' ')}: {v}" for k, v in (s.get("traits") or {}).items())
        for n, s in zip(numbers, slots))
    groups = ""
    if communities:
        groups = "\nCommunities people in this segment may belong to:\n" + "\n".join(
            f"- {c.name} ({c.kind}): {c.description} Norms: {c.norms}" for c in communities) + "\n"
    extra = []
    if any(not s.get("city") for s in slots):
        extra.append('"city": "... (only when no city is given)"')
    if any("education" not in (s.get("traits") or {}) for s in slots):
        extra.append('"education": "..."')
    if any("income" not in (s.get("traits") or {}) for s in slots):
        extra.append('"income_level": "low|lower-middle|middle|upper-middle|high"')
    avoid = ", ".join(list(avoid_names)[-60:])
    return f"""Write {len(slots)} distinct synthetic people for this audience segment of a social media simulation.

Segment: {seg.label}
Country: {seg.country or "as implied by the segment"}
Role: {seg.role or seg.label}
Languages: {", ".join(seg.languages) or "local norms"}
Platforms they use: {", ".join(seg.platforms) or "typical for their age and country"}
What we know about this group: {seg.notes or "see context"}
{groups}
Simulation requirement:
{requirement[:2500]}

Context from the seed documents:
{context[:3500]}

Use exactly these fixed demographics; keep each person's number as "i":
{people}

Rules:
- Invent a realistic full name for each person: given name and family name common for their country,
  region, religion mix and generation; no two people share a name.{f" Do not reuse or resemble these names: {avoid}." if avoid else ""}
- Never use a real, famous or public person's name or biography.
- Let where they live shape the details: small-town and rural people have different jobs, incomes, prices, data
  plans, shops and distances than metro people; do not make everyone an office worker in a tower.
- Make them genuinely different: let the fixed traits (upbringing, education, income, thinking style,
  tech comfort, media diet) shape their goals, family situation, trust in ads, what they already know
  about the topic, and how they would react (some enthusiastic, some sceptical, some indifferent or busy).
- Give each person one believable contradiction (e.g. a price-hunter who splurges on one thing, a sceptic
  who trusts one particular source) so nobody reads like a stereotype.
- Write their voice the way they actually post: language mix, slang or formality, typical length.

Return compact JSON on one line, no code fence: {{"personas": [{{"i": N, "name": "...", {", ".join(extra) + ", " if extra else ""}
  "occupation": "...", "household": "...", "languages": ["..."], "platform_habits": "...", "decision_role": "...",
  "attitude": "...", "concerns": ["..."], "what_persuades_them": "...", "contradiction": "...", "voice": "...",
  "example_post": "...", "interested_topics": ["..."],
  "bio": "one-line social media bio",
  "persona": "a description of at least 150 and at most 250 words combining all of the above and how they relate to the topic"
}}]}}"""


INTERVIEW_QUESTIONS = [
    "Where did you grow up, and what was home like?",
    "Who is in your family now, and who do you live with?",
    "How is money this month? What do you spend on first, and what do you cut?",
    "Walk me through a typical weekday, hour by hour.",
    "What phone do you use, and what is your data plan like?",
    "What was the last thing you bought online, and why that one?",
    "Tell me about a time you got scammed or badly disappointed by a purchase.",
    "Who do you ask before spending real money on something new?",
    "What did you do last weekend?",
    "What do you post or share about online, and where?",
    "What annoys you most in ads?",
    "What is something you would never post about?",
]
INTERVIEW_BATCH = 4


def _voices_block(voices: Optional[List[Dict[str, Any]]], country: str = "", n: int = 4) -> str:
    """Real quotes from public reviews/threads (research step) that people like these would have read or written."""
    if not voices:
        return ""
    from .research import pick_voices
    picks = pick_voices(voices, n, country)
    if not picks:
        return ""
    lines = "\n".join(f"- \"{v['text'][:220]}\" ({v['source']})" for v in picks)
    return f"\nWhat real people wrote in public reviews and threads about this kind of product (ground the answers in this reality, do not copy it):\n{lines}\n"


def _interview_prompt(people: List[Dict[str, Any]], context: str, voices: Optional[List[Dict[str, Any]]] = None) -> str:
    """The life interview. People are numbered; each row carries its number ("i") and the 12 answers in order,
    so the questions are not written back for every person."""
    cards = "\n".join(
        f"{p.get('i', i + 1)}. {p['name']}: age {p.get('age')}, {p.get('gender')}, {p.get('occupation')}, "
        f"{p.get('city') or ''} {p.get('country') or ''}; segment {p.get('segment')}; "
        f"languages {', '.join(p.get('languages') or []) or 'local'}; upbringing {p.get('upbringing')}; "
        f"education {p.get('education')}; income {p.get('income_level') or p.get('income')}; "
        f"thinking style {p.get('thinking_style')}; tech comfort {p.get('tech_comfort')}; "
        f"media diet {p.get('media_diet')}; attitude: {p.get('attitude')}"
        for i, p in enumerate(people))
    qs = "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(INTERVIEW_QUESTIONS))
    return f"""This is a life interview with {len(people)} fictional people, for a market simulation. Answer every
question as each person would, in their own words and in the language mix they actually speak day to day
(e.g. Hinglish, Taglish, Nepali-English, Bahasa gaul), 1-3 sentences each, concrete and specific (names of
neighbourhoods, prices in local currency, phone models, apps). Keep each person consistent with their card and
different from the others. Never use real or public people.

Context of the simulation (what they will later react to):
{context[:1500]}
{_voices_block(voices, str((people[0] or {}).get("country") or "") if people else "")}
People:
{cards}

Questions:
{qs}

Return compact JSON on one line, no code fence: {{"interviews": [{{"i": <person number>,
  "a": ["answer to Q1", "answer to Q2", ... all {len(INTERVIEW_QUESTIONS)} answers in order],
  "phone": "phone model and age", "data_plan": "wifi at home / prepaid data / unlimited...",
  "summary": "at least 100 and about 120 words in the first person, in their own voice, summarising who they are,
  their money situation, how they decide on purchases and what they distrust"}}]}}"""


# --- research-backed second pass: adaptive probes, product questions and the structured BDE card ---
# Park et al. 2024 (interview-grounded agents), arXiv 2608.20344 (Background / Decision procedure / Evaluation
# structure beats raw transcripts), arXiv 2509.19088 (hyper-rationality, stereotyping).

PROBE_RULES = [
    # (regex on the money answer / scam answer / who-they-ask answer, probe question)
    ("money", r"tight|no savings|cut|short|loan|udhaar|utang|kulang|stretch|struggle|barely|paycheck|salary.*(end|late)",
     "When money is tight, what is the very last thing you give up, and the first thing you stop paying for?"),
    ("scam", r"scam|fraud|fake|cheated|lost|never (got|received)|refund|duplicate|chori|loko|dhoka",
     "Since that happened, what exactly do you check before paying anyone online now?"),
    ("ask", r"wife|husband|partner|mother|father|parents|family|boss|friend|colleague|brother|sister|biwi|asawa",
     "What does that person usually say when you want to buy something new, and when did you ignore them?"),
    ("ads", r"annoy|hate|skip|fake|loud|too much|repeat|irrelevant|bakwas|nakakainis",
     "Tell me about the last ad that actually got you to buy something. What was different about it?"),
]
DEFAULT_PROBES = [
    "What did you buy in the last year that you now regret, and what did you learn from it?",
    "When did you last try something new because someone you know used it first?",
]


def choose_probes(answers: List[Dict[str, Any]]) -> List[str]:
    """Two follow-up questions picked from the first answers (money, scam, who-they-ask, ads), else defaults."""
    text = {("Q3" if i == 2 else "Q7" if i == 6 else "Q8" if i == 7 else "Q11" if i == 10 else x.get("q")): str(x.get("a") or "")
            for i, x in enumerate(answers)}
    joined = {"money": text.get("Q3", ""), "scam": text.get("Q7", ""), "ask": text.get("Q8", ""), "ads": text.get("Q11", "")}
    picks = [q for key, pat, q in PROBE_RULES if re.search(pat, joined.get(key, ""), re.I)]
    for q in DEFAULT_PROBES:
        if len(picks) >= 2:
            break
        picks.append(q)
    return picks[:2]


def product_questions(product: Optional[Dict[str, Any]]) -> List[str]:
    """Three product-specific interview questions from the product profile (Phase A), or none."""
    if not product or not (product.get("name") or product.get("one_liner")):
        return []
    name = product.get("name") or "this product"
    what = product.get("one_liner") or product.get("category") or "it"
    offer = product.get("offer") or "a trial"
    return [f"Have you ever used anything like {what}? What happened, and why did you stop or keep going?",
            f"If {name} offered you {offer} this week, what would make you try it, and what would stop you?",
            f"What would you expect to pay for {what}, and at what price would you walk away?"]


BDE_SCHEMA = {
    "background": {"who": "one sentence: who they are and what fills their days", "knows": "what they know about this product category",
                   "believes": "2-3 beliefs that shape how they buy", "acquiescence": "low|medium|high (how much they agree to be polite)",
                   "social_desirability": "low|medium|high (how much they say what sounds good)",
                   "says_vs_does": "one sentence on where their words and actions differ"},
    "decision_procedure": {"who_they_ask": "...", "speed": "impulsive|considered|slow", "style": "maximiser|satisficer",
                           "risk": "averse|neutral|seeking", "patience": "low|medium|high",
                           "triggers": ["what makes them act now"], "stoppers": ["what makes them close the tab"]},
    "evaluation": {"monthly_discretionary": "amount in local currency", "value_priorities": ["top 3 things they pay for"],
                   "pays_for": ["things they already pay for monthly"], "never_pays_for": ["..."],
                   "dealbreakers": ["..."], "trust_cues": ["what makes them trust a brand"]},
}


# the decision card with short keys (clean_bde maps them back through _SECTION_ALIASES and _FIELD_ALIASES)
BDE_SHORT_SCHEMA = {
    "b": {"who": "one sentence: who they are and what fills their days", "knows": "what they know about this product category",
          "believes": "2-3 beliefs that shape how they buy", "acq": "low|medium|high (agrees to be polite)",
          "sd": "low|medium|high (says what sounds good)", "svd": "one sentence on where their words and actions differ"},
    "d": {"ask": "who they ask", "spd": "impulsive|considered|slow", "style": "maximiser|satisficer",
          "risk": "averse|neutral|seeking", "pat": "low|medium|high", "trig": ["what makes them act now"],
          "stop": ["what makes them close the tab"]},
    "e": {"spare": "monthly spare money in local currency", "prio": ["top 3 things they pay for"],
          "pays": ["things they already pay for monthly"], "never": ["..."], "deal": ["deal-breakers"],
          "trust": ["what makes them trust a brand"]},
}


def _probe_prompt(people: List[Dict[str, Any]], answers_by_name: Dict[str, List[Dict[str, Any]]],
                  probes_by_name: Dict[str, List[str]], product_qs: List[str], context: str) -> str:
    """Follow-ups and the decision card. People are numbered ("i"); answers come back in question order."""
    blocks = []
    for i, p in enumerate(people):
        qa = "\n".join(f"  {x['q']}: {x['a']}" for x in answers_by_name.get(p["name"], [])[:12])
        qs = probes_by_name.get(p["name"], []) + product_qs
        blocks.append(f"{p['name']} ({p.get('age')}, {p.get('occupation')}, {p.get('city') or ''} {p.get('country') or ''}) "
                      f"[person {p.get('i', i + 1)}]:\n"
                      f"Earlier answers:\n{qa}\nNow answer:\n" + "\n".join(f"  P{j + 1}. {q}" for j, q in enumerate(qs)))
    return f"""Second part of a life interview with {len(people)} fictional people (market simulation). First answer the
follow-up questions as each person would, in their own voice and everyday language mix, 1-3 sentences, concrete
(amounts in local currency, names of apps and places). People are not fully consistent or rational: let habits,
mood and money pressure show. Then fill the structured card from EVERYTHING they said: the card describes this one
person, never their group; copy their own words where you can.

Context (what they will react to later):
{context[:1200]}

{chr(10).join(blocks)}

Return compact JSON on one line, no code fence: {{"people": [{{"i": <person number>,
  "p": ["answer to P1", "answer to P2", ... in order],
  "bde": {json.dumps(BDE_SHORT_SCHEMA, ensure_ascii=False)}}}]}}"""


_SECTION_ALIASES = {
    "background": ("background", "b", "profile", "who_they_are", "bg"),
    "decision_procedure": ("decision_procedure", "decisionprocedure", "decision", "decision_making", "decisions", "d", "how_they_decide", "dp"),
    "evaluation": ("evaluation", "evaluation_profile", "e", "ep", "what_they_pay_for", "values", "evaluation_criteria"),
}
_FIELD_ALIASES = {
    "who": ("who", "who_they_are", "summary", "identity", "about"), "knows": ("knows", "knowledge", "category_knowledge", "what_they_know"),
    "believes": ("believes", "beliefs", "belief", "worldview"), "acquiescence": ("acquiescence", "agreeableness_to_please", "politeness", "acq"),
    "social_desirability": ("social_desirability", "socially_desirable", "sd"), "says_vs_does": ("says_vs_does", "stated_vs_behaviour", "stated_vs_behavior", "say_do_gap", "says_vs_behaviour", "svd"),
    "who_they_ask": ("who_they_ask", "asks", "influencers", "who_they_consult", "ask"), "speed": ("speed", "decision_speed", "spd"),
    "style": ("style", "maximiser_or_satisficer", "maximizer_or_satisficer"), "risk": ("risk", "risk_attitude", "risk_tolerance"),
    "patience": ("patience", "pat",), "triggers": ("triggers", "acts_when", "buy_triggers", "trig"), "stoppers": ("stoppers", "stops_when", "blockers", "stop"),
    "monthly_discretionary": ("monthly_discretionary", "spare_money", "discretionary_budget", "budget", "spare"),
    "value_priorities": ("value_priorities", "priorities", "values", "prio"), "pays_for": ("pays_for", "subscriptions", "already_pays_for", "pays"),
    "never_pays_for": ("never_pays_for", "won't_pay_for", "wont_pay_for", "never"), "dealbreakers": ("dealbreakers", "deal_breakers", "deal"),
    "trust_cues": ("trust_cues", "trusts_when", "trust_signals", "trust"),
}


def _norm_key(k: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(k).strip().lower()).strip("_")


def parse_discretionary_amount(text: Any) -> Optional[float]:
    """Extract numeric monthly discretionary amount from a currency string like 'NPR 2,000' or '$120/mo'."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text) if text >= 0 else None
    s = str(text or "").strip()
    if not s:
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?", s)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
        if m.group(2):
            val *= 1000.0
        return val
    except ValueError:
        return None


def clean_bde(raw: Any) -> Optional[Dict[str, Any]]:
    """Accept the BDE card in the shapes models actually return: the schema, capitalised or aliased section and
    field names, a flat object, sections written as prose, or the whole card as prose."""
    if isinstance(raw, str):
        if len(raw.strip()) < 40:                         # a word or two is not a card
            return None
        raw = {"background": {"who": raw.strip()}}
    if not isinstance(raw, dict):
        return None
    norm = {_norm_key(k): v for k, v in raw.items()}
    sections: Dict[str, Dict[str, Any]] = {}
    for section, aliases in _SECTION_ALIASES.items():
        val = next((norm[a] for a in aliases if a in norm), None)
        if isinstance(val, str) and val.strip():
            val = {list(BDE_SCHEMA[section])[0]: val.strip()}
        sections[section] = {_norm_key(k): v for k, v in val.items()} if isinstance(val, dict) else {}
    if not any(sections.values()):                       # a flat card: route each field to its section
        for section, fields in BDE_SCHEMA.items():
            for k in fields:
                for a in _FIELD_ALIASES.get(k, (k,)):
                    if a in norm:
                        sections[section][k] = norm[a]
                        break
    out: Dict[str, Any] = {}
    for section, fields in BDE_SCHEMA.items():
        src_raw = sections.get(section) or {}
        src = {}
        for k in fields:
            for a in _FIELD_ALIASES.get(k, (k,)):
                if a in src_raw:
                    src[k] = src_raw[a]
                    break
        sec: Dict[str, Any] = {}
        for k, spec in fields.items():
            v = src.get(k)
            if isinstance(spec, list):
                sec[k] = [str(x).strip()[:120] for x in (v if isinstance(v, list) else [v] if v else []) if str(x).strip()][:5]
            else:
                sec[k] = str(v or "").strip()[:240]
        out[section] = sec
    if not any(any(v for v in sec.values()) for sec in out.values()):
        return None
    disc_num = parse_discretionary_amount((out.get("evaluation") or {}).get("monthly_discretionary"))
    if disc_num is not None:
        out["evaluation"]["discretionary_budget_num"] = disc_num
    return out


def identity_seed(name: str, salt: int = 0) -> int:
    """A person's stable seed: the same name gives the same habits in every test, study cell and rerun."""
    import zlib
    return (zlib.crc32(str(name or "").encode("utf-8")) ^ (salt * 2654435761)) & 0xFFFFFFFF


def stable_habits(name: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Habits that belong to the person, not to an experiment: ad avoidance, how often they comment, click ads,
    share, open marketing email. Seeded by identity (research note: separate stable traits from episode randomness)."""
    rng = random.Random(identity_seed(name))
    style = str(attrs.get("thinking_style") or "").lower()
    avoid = rng.betavariate(2.2, 1.8)
    if "sceptical" in style or "skeptical" in style or "risk-averse" in style or "traditional" in style:
        avoid = min(1.0, avoid + 0.15)
    if "early adopter" in style or "status" in style:
        avoid = max(0.0, avoid - 0.2)
    settlement = str(attrs.get("settlement") or "")
    online = {"metro": 1.0, "city": 0.95, "town": 0.85, "rural": 0.7}.get(settlement, 0.9)
    return {"ad_avoidance": round(avoid, 2),
            "comments": rng.choices(["a few times a week", "about once a week", "about once a month", "a few times a year", "almost never"],
                                    [0.07, 0.15, 0.28, 0.3, 0.2])[0],
            "clicks_ads": rng.choices(["almost never", "rarely", "sometimes"], [0.45, 0.4, 0.15])[0],
            "shares": rng.choices(["often", "sometimes", "rarely"], [0.15, 0.4, 0.45])[0],
            "opens_promo_email": rng.choices(["almost never", "rarely", "sometimes", "often"], [0.3, 0.35, 0.25, 0.1])[0],
            "online_hours": round(rng.uniform(1.0, 6.0) * online, 1),
            "best_time": rng.choice(["early morning", "commute", "lunch", "evening", "late night"])}


def render_bde(bde: Optional[Dict[str, Any]], limit: int = 700) -> str:
    """Compact text for prompts: how this person decides and what they pay for."""
    if not bde:
        return ""
    b, d, e = bde.get("background") or {}, bde.get("decision_procedure") or {}, bde.get("evaluation") or {}
    bits = []
    if b.get("believes"):
        bits.append(f"Beliefs: {b['believes']}")
    if b.get("says_vs_does"):
        bits.append(f"Says vs does: {b['says_vs_does']}")
    dp = ", ".join(x for x in (d.get("speed"), d.get("style"), f"risk {d['risk']}" if d.get("risk") else "",
                               f"patience {d['patience']}" if d.get("patience") else "") if x)
    if dp or d.get("who_they_ask"):
        bits.append(f"Decides: {dp}" + (f"; asks {d['who_they_ask']}" if d.get("who_they_ask") else ""))
    if d.get("triggers"):
        bits.append("Acts when: " + "; ".join(d["triggers"]))
    if d.get("stoppers"):
        bits.append("Stops when: " + "; ".join(d["stoppers"]))
    if e.get("monthly_discretionary"):
        bits.append(f"Spare money: {e['monthly_discretionary']}")
    if e.get("value_priorities"):
        bits.append("Pays for: " + "; ".join(e["value_priorities"]))
    if e.get("dealbreakers"):
        bits.append("Dealbreakers: " + "; ".join(e["dealbreakers"]))
    if e.get("trust_cues"):
        bits.append("Trusts when: " + "; ".join(e["trust_cues"]))
    return " ".join(bits)[:limit]


ATTEMPTS = 3                     # one ask plus up to two asks for whoever is still missing
DEEP_BATCH = max(1, int(os.environ.get("MM_DEEP_BATCH") or 4))   # people per persona, interview and follow-up call


def _interview_card(e: EntityNode) -> Dict[str, Any]:
    a = e.attributes or {}
    prof = a.get(SYNTHETIC_PROFILE_KEY) or {}
    return {"name": e.name, "age": prof.get("age"), "gender": prof.get("gender"), "occupation": a.get("occupation"),
            "city": a.get("city"), "country": a.get("country"), "segment": a.get("segment"),
            "languages": a.get("languages"), "upbringing": a.get("upbringing"), "education": a.get("education"),
            "income_level": a.get("income_level"), "income": a.get("income"), "thinking_style": a.get("thinking_style"),
            "tech_comfort": a.get("tech_comfort"), "media_diet": a.get("media_diet"), "attitude": a.get("attitude")}


def _match_rows(rows: List[Dict[str, Any]], batch: List[Any], name_of: Callable[[Any], str] = lambda e: getattr(e, "name", "") or ""
                ) -> Dict[int, Dict[str, Any]]:
    """Answer rows by position in `batch`: the row's number ("i", 1-based), else its name, else its order when
    the counts match."""
    names = {str(name_of(e)).strip().lower(): k for k, e in enumerate(batch)}
    out: Dict[int, Dict[str, Any]] = {}
    for pos, r in enumerate(rows):
        k = None
        try:
            k = int(r.get("i")) - 1
        except (TypeError, ValueError):
            k = None
        if k is None or not 0 <= k < len(batch):
            k = names.get(str(r.get("name") or "").strip().lower())
        if k is None and len(rows) == len(batch):
            k = pos
        if k is not None and 0 <= k < len(batch) and k not in out:
            out[k] = r
    return out


def apply_interview(e: EntityNode, r: Dict[str, Any], prov: str = "", mod: str = "") -> bool:
    """Attach a life interview row (answers in order as "a", or the older [{q, a}] form). False when it has none."""
    raw = r.get("a") if isinstance(r.get("a"), list) else r.get("answers")
    answers = []
    for i, x in enumerate(raw or []):
        q, a = (str(x.get("q") or f"Q{i + 1}"), str(x.get("a") or "").strip()) if isinstance(x, dict) else (f"Q{i + 1}", str(x or "").strip())
        if a:
            answers.append({"q": q, "a": a})
    if not answers:
        return False
    summary = str(r.get("summary") or "").strip()
    e.attributes["interview"] = answers
    (e.attributes.setdefault("provenance", {}))["interview"] = f"synthetic: model-written life interview ({prov}/{mod})" if prov else "synthetic: model-written life interview"
    if summary:
        e.attributes["interview_summary"] = summary[:1200]
    if r.get("phone"):
        e.attributes["phone"] = str(r["phone"])[:120]
    if r.get("data_plan"):
        e.attributes["data_plan"] = str(r["data_plan"])[:120]
    prof = e.attributes.get(SYNTHETIC_PROFILE_KEY)
    if prof and summary:
        prof["persona"] = f"{prof['persona']} In their own words: {summary}"
    return True


def apply_probes(e: EntityNode, r: Dict[str, Any], prov: str = "", mod: str = "") -> bool:
    """Attach follow-up answers ("p" in order, or the older probe_answers) and the decision card."""
    raw = r.get("p") if isinstance(r.get("p"), list) else r.get("probe_answers")
    pa = []
    for i, x in enumerate(raw or []):
        q, a = (str(x.get("q") or f"P{i + 1}"), str(x.get("a") or "").strip()) if isinstance(x, dict) else (f"P{i + 1}", str(x or "").strip())
        if a:
            pa.append({"q": q, "a": a})
    bde = clean_bde(r.get("bde") or r.get("BDE") or r.get("card"))
    if not pa and not bde:
        return False
    if pa:
        e.attributes["interview"] = (e.attributes.get("interview") or []) + pa
    if bde:
        e.attributes["bde"] = bde
        (e.attributes.setdefault("provenance", {}))["bde"] = f"synthetic: extracted from the interview ({prov}/{mod})" if prov else "synthetic: extracted from the interview"
        prof = e.attributes.get(SYNTHETIC_PROFILE_KEY)
        if prof:
            prof["persona"] = f"{prof['persona']} How I decide: {render_bde(bde, 500)}"
    return True


def _ask_rows(caller: Any, lane: int, build_prompt: Callable[[List[Any]], str], batch: List[Any], key: str,
              apply: Callable[[Any, Dict[str, Any], str, str], bool], what: str, max_tokens: int, temperature: float) -> List[Any]:
    """Ask for `batch`, apply each usable row, then ask again only for whoever is still missing (ATTEMPTS in all).
    Returns the people still missing. Nobody is filled in by code."""
    pending = list(batch)
    for attempt in range(ATTEMPTS):
        if not pending:
            break
        if attempt:
            time.sleep(RETRY_PAUSE_S * attempt)
        prompt = build_prompt(pending)
        try:
            answer = caller.text(lane, SYSTEM_PROMPT, prompt, max_tokens=max_tokens,
                                 temperature=max(0.4, temperature - 0.2 * attempt))
            data = parse_json_block(answer[0])
        except Exception as e:  # noqa: BLE001 - asked again below, then reported missing
            logger.warning(f"{what}: {len(pending)} people, attempt {attempt + 1}: {str(e)[:160]}")
            continue
        rows = data.get(key) if isinstance(data, dict) else data
        rows = [r for r in (rows or []) if isinstance(r, dict)]
        done = {k for k, r in _match_rows(rows, pending).items() if apply(pending[k], r, answer[1], answer[2])}
        if done:
            caller.remember(lane, SYSTEM_PROMPT, prompt, answer)
        pending = [e for k, e in enumerate(pending) if k not in done]
    return pending


def interview_batch(caller: Any, lane: int, batch: List[EntityNode], context: str,
                    voices: Optional[List[Dict[str, Any]]], product_qs: List[str], probes: bool = True) -> Tuple[int, int]:
    """The life interview for one batch, then its follow-ups and decision card straight away (no waiting for other
    batches). Returns (interviewed, followed up)."""
    def iv_prompt(people: List[EntityNode]) -> str:
        return _interview_prompt([{**_interview_card(e), "i": k + 1} for k, e in enumerate(people)], context, voices)
    _ask_rows(caller, lane, iv_prompt, batch, "interviews", apply_interview, "interview", 9000, 0.9)
    interviewed = [e for e in batch if e.attributes.get("interview")]
    if not probes or not interviewed:
        return len(interviewed), 0

    def pr_prompt(people: List[EntityNode]) -> str:
        return _probe_prompt([{**_interview_card(e), "i": k + 1} for k, e in enumerate(people)],
                             {e.name: e.attributes.get("interview") or [] for e in people},
                             {e.name: choose_probes(e.attributes.get("interview") or []) for e in people}, product_qs, context)
    missing = _ask_rows(caller, lane, pr_prompt, interviewed, "people", apply_probes, "follow-ups", 9000, 0.8)
    return len(interviewed), len(interviewed) - len(missing)


def run_interviews(client, model: str, entities: List[EntityNode], context: str,
                   progress: Optional[Callable[[int, int, str], None]] = None, parallel: int = 4,
                   product: Optional[Dict[str, Any]] = None, probes: bool = True,
                   voices: Optional[List[Dict[str, Any]]] = None,
                   gate: Optional[threading.Semaphore] = None, caller: Any = None) -> int:
    """Interview synthetic personas in batches; attach answers, phone/data plan and a first-person summary, then
    (probes=True) adaptive follow-ups, product questions and the structured BDE card (background / decision
    procedure / evaluation). Each person is interviewed by the provider that wrote them, through that provider's
    lane. Returns the number of people interviewed. `gate` is accepted for older callers; the lanes bound the calls."""
    from .fast_population import Caller
    caller = caller or Caller(client, model, parallel)
    people = [e for e in entities if PERSONA_LABEL in e.labels]
    per_writer: Dict[int, List[List[EntityNode]]] = {}
    for e in people:
        lane = caller.lane_of(str((e.attributes or {}).get("model_provider") or ""))
        group = per_writer.setdefault(lane, [[]])
        if len(group[-1]) >= INTERVIEW_BATCH:
            group.append([])
        group[-1].append(e)
    # interleaved across providers, so each provider's lane has work from the start
    batches = [(lane, v[i]) for i in range(max((len(v) for v in per_writer.values()), default=0))
               for lane, v in sorted(per_writer.items()) if i < len(v) and v[i]]
    if not batches:
        return 0
    product_qs = product_questions(product)
    done = [0]
    lock = threading.Lock()

    def one(item: Tuple[int, List[EntityNode]]) -> int:
        lane, batch = item
        n, _ = interview_batch(caller, lane, batch, context, voices, product_qs, probes)
        with lock:
            done[0] += len(batch)
            d = done[0]
        if progress:
            progress(d, len(people), "interviews")
        return n

    workers = max(1, sum(ln.max_limit for ln in caller.lanes) * 2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return sum(pool.map(one, batches))


def diversity_report(entities: List[EntityNode]) -> Dict[str, Any]:
    """Per segment: how many people share an occupation, city, phone or contradiction, and a 0-1 variety score
    (normalised entropy of occupations). Flags segments that read like one stereotype repeated."""
    import math
    from collections import Counter
    by_seg: Dict[str, List[EntityNode]] = {}
    for e in entities:
        if PERSONA_LABEL in e.labels:
            by_seg.setdefault(str((e.attributes or {}).get("segment") or "?"), []).append(e)
    rows = []
    for seg, people in by_seg.items():
        n = len(people)

        def dup(key: str) -> int:
            c = Counter(str((e.attributes or {}).get(key) or "").strip().lower() for e in people)
            return sum(v - 1 for k, v in c.items() if k and v > 1)

        occ = Counter(str((e.attributes or {}).get("occupation") or "").strip().lower() for e in people)
        ent = -sum((v / n) * math.log(v / n) for v in occ.values() if v) if n > 1 else 0.0
        variety = round(ent / math.log(n), 2) if n > 1 else 1.0
        row = {"segment": seg, "n": n, "variety": variety, "dup_occupation": dup("occupation"), "dup_city": dup("city"),
               "dup_phone": dup("phone"), "dup_contradiction": dup("contradiction")}
        row["flag"] = n >= 4 and (variety < 0.6 or row["dup_occupation"] > n // 2)
        rows.append(row)
    return {"segments": rows, "flagged": [r["segment"] for r in rows if r["flag"]]}


def fix_duplicates(entities: List[EntityNode], rng: random.Random) -> int:
    """Code-only repair for the commonest stereotype: several people in a segment with the same occupation and
    city. The duplicates get another city from the segment (round-robin) and a numbered variant of the role
    ('shop owner' -> 'shop owner (second-hand phones)'). Returns how many people were changed."""
    changed = 0
    by_seg: Dict[str, List[EntityNode]] = {}
    for e in entities:
        if PERSONA_LABEL in e.labels:
            by_seg.setdefault(str((e.attributes or {}).get("segment") or "?"), []).append(e)
    variants = ["(part-time)", "(night shift)", "(freelance)", "(family business)", "(junior)", "(senior)", "(contract)"]
    for people in by_seg.values():
        cities = sorted({str((e.attributes or {}).get("city") or "") for e in people} - {""})
        seen: Dict[tuple, int] = {}
        for e in people:
            a = e.attributes or {}
            key = (str(a.get("occupation") or "").lower(), str(a.get("city") or "").lower())
            k = seen.get(key, 0)
            seen[key] = k + 1
            if k == 0 or not key[0]:
                continue
            if len(cities) > 1:
                a["city"] = cities[(cities.index(a.get("city")) + k) % len(cities)] if a.get("city") in cities else rng.choice(cities)
            else:
                a["occupation"] = f"{a['occupation']} {variants[(k - 1) % len(variants)]}"
                prof = a.get(SYNTHETIC_PROFILE_KEY)
                if prof:
                    prof["profession"] = a["occupation"]
            changed += 1
    return changed


def population_weights(entities: List[EntityNode], population: Optional[Dict[str, Any]]) -> int:
    """Raking-lite: `population` = {country: {"age": {"18-24": share, ...}, "gender": {"female": share, ...}}}.
    Each persona gets weight = product over dimensions of target share / sample share for its cell, normalised
    to mean 1 within the country. Aggregates that honour `weight` then reflect the real population mix
    (backstory conditioning + demographic resampling, Anthology / Anamnesis). Returns how many people got a weight."""
    if not population:
        return 0
    from collections import Counter, defaultdict

    def band(age: Any) -> str:
        try:
            a = int(age)
        except (TypeError, ValueError):
            return "?"
        for lo, hi in ((18, 24), (25, 34), (35, 44), (45, 54), (55, 64)):
            if lo <= a <= hi:
                return f"{lo}-{hi}"
        return "65+" if a >= 65 else "<18"

    people = [e for e in entities if PERSONA_LABEL in e.labels]
    by_country: Dict[str, List[EntityNode]] = defaultdict(list)
    for e in people:
        by_country[str((e.attributes or {}).get("country") or "")].append(e)
    n_weighted = 0
    for country, group in by_country.items():
        target = population.get(country) or population.get(country.lower()) or {}
        if not target:
            continue
        weights = {}
        for dim, getter in (("age", lambda e: band(((e.attributes or {}).get(SYNTHETIC_PROFILE_KEY) or {}).get("age"))),
                            ("gender", lambda e: str(((e.attributes or {}).get(SYNTHETIC_PROFILE_KEY) or {}).get("gender") or "").lower())):
            shares = {str(k).lower(): float(v) for k, v in (target.get(dim) or {}).items()}
            if not shares:
                continue
            tot = sum(shares.values()) or 1.0
            sample = Counter(getter(e) for e in group)
            for e in group:
                cell = getter(e)
                t = shares.get(str(cell).lower(), 0.0) / tot
                s_ = sample[cell] / len(group)
                weights[e.uuid] = weights.get(e.uuid, 1.0) * ((t / s_) if (t and s_) else 1.0)
        if not weights:
            continue
        mean = sum(weights.values()) / len(weights)
        for e in group:
            e.attributes["weight"] = round(max(0.2, min(5.0, weights.get(e.uuid, 1.0) / mean)), 3)
            n_weighted += 1
    return n_weighted


def _dedupe_name(name: str, taken: set) -> str:
    base = name.strip() or "Unnamed"
    candidate, n = base, 2
    while candidate.lower() in taken:
        candidate = f"{base} {n}"
        n += 1
    taken.add(candidate.lower())
    return candidate


def provider_shares(sizes: List[int], n_slots: int) -> List[int]:
    """Slot for each persona job so every provider in a pool writes the same number of people (within one job),
    and each segment is split across the providers: the job goes to the provider with the fewest people so far."""
    counts = [0] * max(1, n_slots)
    out = []
    for i, size in enumerate(sizes):
        start = i % len(counts)
        idx = min(range(len(counts)), key=lambda k: (counts[k], (k - start) % len(counts)))
        counts[idx] += size
        out.append(idx)
    return out


def generate_personas(client, model: str, spec: PersonaSpec, requirement: str, context: str,
                      progress: Optional[Callable[[int, int, str], None]] = None,
                      parallel: int = 4, product: Optional[Dict[str, Any]] = None,
                      voices: Optional[List[Dict[str, Any]]] = None) -> List[EntityNode]:
    """Synthetic individual entities for every segment, plus community accounts when communities exist."""
    rng = random.Random(spec.seed)
    if spec.auto and not spec.segments:
        segs, comms = plan_segments(client, model, requirement, context, spec.auto_total,
                                    with_communities=spec.auto_communities and not spec.communities)
        spec.segments = segs
        if not spec.communities:
            spec.communities = comms
        logger.info(f"persona planner: {len(segs)} segments, {sum(s.count for s in segs)} personas, "
                    f"{len(spec.communities)} communities")

    requested = sum(s.count for s in spec.segments)
    if spec.depth == "fast" or (spec.depth == "auto" and requested > FAST_ABOVE):
        entities, taken, stats = _write_fast(client, model, spec, requirement, context, rng, progress, parallel,
                                             product, voices)
        return _finish_population(entities, spec, rng, taken, stats)

    entities, taken, stats = _write_full(client, model, spec, requirement, context, rng, progress, parallel,
                                         product, voices)
    return _finish_population(entities, spec, rng, taken, stats)


class DuplicateGuard:
    """fix_duplicates, applied batch by batch: a person whose (occupation, city) is already taken in their segment
    gets another city of the segment (or a numbered variant of the role) before their interview is written."""

    VARIANTS = ["(part-time)", "(night shift)", "(freelance)", "(family business)", "(junior)", "(senior)", "(contract)"]

    def __init__(self, segments: Sequence[PersonaSegment]):
        self.seen: Dict[str, Dict[tuple, int]] = {}
        self.cities: Dict[str, List[str]] = {s.label: list(dict.fromkeys(c for c in (s.cities or []) if c)) for s in segments}
        self.lock = threading.Lock()

    def fix(self, people: List[EntityNode]) -> int:
        changed = 0
        with self.lock:
            for e in people:
                a = e.attributes or {}
                seg = str(a.get("segment") or "?")
                cities = self.cities.setdefault(seg, [])
                if a.get("city") and a["city"] not in cities:
                    cities.append(a["city"])
                seen = self.seen.setdefault(seg, {})
                key = (str(a.get("occupation") or "").lower(), str(a.get("city") or "").lower())
                k = seen.get(key, 0)
                seen[key] = k + 1
                if k == 0 or not key[0]:
                    continue
                if len(cities) > 1:
                    a["city"] = cities[(cities.index(a["city"]) + k) % len(cities)] if a.get("city") in cities else cities[k % len(cities)]
                    seen[(key[0], str(a["city"]).lower())] = seen.get((key[0], str(a["city"]).lower()), 0) + 1
                else:
                    a["occupation"] = f"{a['occupation']} {self.VARIANTS[(k - 1) % len(self.VARIANTS)]}"
                    prof = a.get(SYNTHETIC_PROFILE_KEY)
                    if prof:
                        prof["profession"] = a["occupation"]
                changed += 1
        return changed


def _write_full(client, model: str, spec: PersonaSpec, requirement: str, context: str, rng: random.Random,
                progress: Optional[Callable[[int, int, str], None]], parallel: int,
                product: Optional[Dict[str, Any]], voices: Optional[List[Dict[str, Any]]]
                ) -> Tuple[List[EntityNode], set, Dict[str, Any]]:
    """The full-depth people: a persona with its paragraph, the 12-question life interview and the follow-ups with
    the decision card, for everyone. Each batch of DEEP_BATCH people goes straight through the three calls on its
    provider's lane (no waiting for the rest of the segment); every provider writes exactly its share, person by
    person; rows carry their slot number so only missing people are asked again; answers are cached."""
    from .fast_population import Caller
    caller = Caller(client, model, parallel)
    n = caller.n
    jobs: List[Tuple[PersonaSegment, List[Dict[str, Any]], List[CommunitySpec], int]] = []
    offset = 0
    for seg in spec.segments:
        slots = demographic_slots(seg, rng, spec.diversity)
        seg_comms = [c for c in spec.communities if _matches(c, seg.label, seg.country)]
        for lane in range(n):
            mine = [sl for k, sl in enumerate(slots) if (k + offset) % n == lane]
            for start in range(0, len(mine), DEEP_BATCH):
                jobs.append((seg, mine[start:start + DEEP_BATCH], seg_comms, lane))
        offset = (offset + len(slots)) % n
    total = sum(len(j[1]) for j in jobs)
    taken: set = set()
    lock = threading.Lock()
    guard = DuplicateGuard(spec.segments)
    product_qs = product_questions(product)
    results: Dict[int, List[EntityNode]] = {}
    count = {"done": 0, "missing": 0, "fixed": 0, "interviewed": 0, "followed_up": 0}

    def run_job(j: int) -> None:
        seg, slots, comms, lane = jobs[j]
        got: Dict[int, Tuple[Dict[str, Any], str, str]] = {}

        def keep(k_slot: Dict[str, Any], r: Dict[str, Any], prov: str, mod: str) -> bool:
            if not str(r.get("name") or "").strip():
                return False
            got[id(k_slot)] = (r, prov, mod)
            return True

        def prompt(pending: List[Dict[str, Any]]) -> str:
            return _persona_prompt(seg, pending, requirement, context, (), comms,
                                   numbers=list(range(1, len(pending) + 1)))
        missing = _ask_rows(caller, lane, prompt, slots, "personas", keep, f"persona batch {j} ({seg.label})", 9000, 0.8)
        with lock:
            ents = [_to_entity(seg, sl, got[id(sl)][0], taken, j * DEEP_BATCH + k, model_provider=got[id(sl)][1],
                               model_name=got[id(sl)][2]) for k, sl in enumerate(slots) if id(sl) in got]
            count["missing"] += len(missing)
        count["fixed"] += guard.fix(ents)
        iv = fu = 0
        if spec.interview and ents:
            iv, fu = interview_batch(caller, lane, ents, context, voices, product_qs, spec.probes)
        for e in ents:
            e.attributes["depth"] = "interviewed" if e.attributes.get("interview") else "profile"
        with lock:
            results[j] = ents
            count["done"] += len(slots)
            count["interviewed"] += iv
            count["followed_up"] += fu
            d = count["done"]
        if progress:
            progress(d, total, seg.label)

    by_lane: Dict[int, List[int]] = {}
    for j, job in enumerate(jobs):
        by_lane.setdefault(job[3], []).append(j)
    executors = {lane: ThreadPoolExecutor(max_workers=max(1, caller.lanes[lane].max_limit * 2)) for lane in by_lane}
    try:
        futures = [executors[lane].submit(run_job, j) for lane, js in by_lane.items() for j in js]
        for f in futures:
            f.result()
    finally:
        for ex in executors.values():
            ex.shutdown(wait=True)
    entities = [e for j in range(len(jobs)) for e in results.get(j, [])]
    st = caller.stats()
    logger.info(f"persona planner (full): {len(entities)} people, {count['missing']} not written, "
                f"{count['interviewed']} interviewed, {count['followed_up']} followed up; lanes {st['lanes']}; cache {st['cache']}")
    return entities, taken, {"fixed": count["fixed"], "failed": count["missing"], "total": total,
                             "interviewed": count["interviewed"], **st}




def _write_fast(client, model: str, spec: PersonaSpec, requirement: str, context: str, rng: random.Random,
                progress: Optional[Callable[[int, int, str], None]], parallel: int,
                product: Optional[Dict[str, Any]], voices: Optional[List[Dict[str, Any]]]
                ) -> Tuple[List[EntityNode], set, Dict[str, Any]]:
    """Cards for everyone in batches (fast_population), then the full life interview for a stratified sample."""
    from . import fast_population as fp
    n_prov = len(getattr(client, "slots", None) or [None])
    jobs, job_slot = [], []
    offset = 0
    for seg in spec.segments:
        slots = demographic_slots(seg, rng, spec.diversity)
        seg_comms = [c for c in spec.communities if _matches(c, seg.label, seg.country)]
        # person k of the segment goes to provider (k + offset) % n: equal shares within every segment, and the
        # offset carries over so the totals stay equal across segments
        for prov in range(n_prov):
            mine = [sl for k, sl in enumerate(slots) if (k + offset) % n_prov == prov]
            for start in range(0, len(mine), fp.CARD_BATCH):
                jobs.append((seg, mine[start:start + fp.CARD_BATCH], seg_comms))
                job_slot.append(prov)
        offset = (offset + len(slots)) % n_prov
    total = sum(len(j[1]) for j in jobs)
    res = fp.write_cards(client, model, jobs, job_slot, requirement, context, parallel=parallel,
                         progress=progress, pause_s=RETRY_PAUSE_S)
    taken: set = set()
    entities: List[EntityNode] = []
    failed = fixed = 0
    for j, (seg, slots, _comms) in enumerate(jobs):
        got = res["rows"].get(j, {})
        failed += len(res["missing"].get(j, []))
        group = []
        for k, slot in enumerate(slots):
            if k not in got:
                continue
            row, prov, mod = got[k]
            e = _to_entity(seg, slot, row, taken, len(entities) + len(group), model_provider=prov, model_name=mod)
            attrs = e.attributes
            attrs[SYNTHETIC_PROFILE_KEY]["persona"] = fp.card_persona(
                e.name, slot["age"], attrs.get("occupation") or seg.label, attrs.get("city") or attrs.get("country") or "",
                row, slot.get("traits") or {})
            bde = clean_bde(row.get("bde_card"))
            prov_tag = f" ({prov}/{mod})" if prov else ""
            if bde:
                attrs["bde"] = bde
                attrs["provenance"]["bde"] = "synthetic: decision card written with the profile" + prov_tag
            attrs["depth"] = "card"
            attrs["provenance"]["interview"] = "not sampled: card only"
            group.append(e)
        fixed += fix_duplicates(group, rng)
        entities.extend(group)
    interviewed = 0
    if spec.interview and entities:
        sample = fp.interview_sample(entities, spec.interview_share, seed=spec.seed)
        interviewed = run_interviews(client, model, sample, context,
                                     progress=(lambda d, t, w: progress(d, t, f"interviews (sample of {t})")) if progress else None,
                                     parallel=parallel, product=product, probes=spec.probes, voices=voices,
                                     gate=threading.BoundedSemaphore(max(1, parallel)))
        for e in sample:
            if e.attributes.get("interview"):
                e.attributes["depth"] = "interviewed"
    logger.info(f"persona planner (fast): {len(entities)} cards, {failed} not written, {interviewed} interviewed; "
                f"lanes {res['lanes']}; cache {res['cache']}")
    return entities, taken, {"fixed": fixed, "failed": failed, "total": total, "interviewed": interviewed,
                             "lanes": res["lanes"], "cache": res["cache"]}


def _finish_population(entities: List[EntityNode], spec: PersonaSpec, rng: random.Random, taken: set,
                       stats: Dict[str, Any]) -> List[EntityNode]:
    """Shared by both depths: real profiles, agent ids, the variety check, population weights and communities."""
    if spec.real_profiles:
        entities.extend(_entities_from_real_profiles(spec.real_profiles, taken, len(entities)))
    for i, e in enumerate(entities):                               # agent id = position: renumber the uuids in order
        e.uuid = f"persona_{i:04d}"
    report = diversity_report(entities)
    if stats.get("fixed") or report["flagged"]:
        logger.info(f"persona planner: stereotype guard changed {stats.get('fixed')} people; low-variety segments: {report['flagged'] or 'none'}")
    if stats.get("failed"):
        logger.warning(f"persona planner: {stats['failed']} of {stats.get('total')} people were not written (their calls failed)")
    if spec.interview:
        logger.info(f"persona planner: interviewed {stats.get('interviewed')} people")
    if spec.population:
        logger.info(f"persona planner: population weights for {population_weights(entities, spec.population)} people")
    if spec.communities:
        assign_communities(entities, spec, rng)
        entities.extend(community_accounts(spec, taken))
    return entities


def _entities_from_real_profiles(real_profiles: List[Dict[str, Any]], taken: set, start_idx: int) -> List[EntityNode]:
    """Build grounded EntityNodes directly from real customer excerpts/records without inventing unobserved attributes."""
    out: List[EntityNode] = []
    for offset, r in enumerate(real_profiles):
        if not isinstance(r, dict):
            continue
        idx = start_idx + offset
        seg_label = str(r.get("segment") or "Grounded Customers").strip()
        name = _dedupe_name(str(r.get("name") or r.get("name_alias") or f"Customer {idx + 1}"), taken)
        country = str(r.get("country") or "").strip()
        city = str(r.get("city") or "").strip()
        age = _int(r.get("age"), 30)
        gender = str(r.get("gender") or "unknown").strip().lower()
        occupation = str(r.get("occupation") or r.get("role") or seg_label).strip()
        excerpts = _str_list(r.get("excerpts"))
        purchases = _str_list(r.get("past_purchases"))
        verbatim = " ".join(f'"{x}"' for x in excerpts[:6])
        persona_text = str(r.get("persona") or r.get("notes") or "").strip()
        if verbatim:
            persona_text = (persona_text + " " if persona_text else "") + f"In their own words (real intake): {verbatim}"
        if not persona_text:
            persona_text = f"{name}, {occupation} from {city or country or seg_label}."
        interview_rows = [{"q": f"Excerpt {i + 1}", "a": ex} for i, ex in enumerate(excerpts)]
        bde = clean_bde(r.get("bde")) if r.get("bde") else None
        details: Dict[str, Any] = {
            "segment": seg_label,
            "city": city,
            "country": country,
            "occupation": occupation,
            "life_stage": _life_stage(age),
            "payday_status": str(r.get("payday_status") or "mid_month"),
            "languages": _str_list(r.get("languages")),
            "past_purchases": purchases,
            "interview": interview_rows,
            "interview_summary": verbatim[:1200] if verbatim else persona_text[:600],
            "bde": bde,
            "model_provider": "grounded",
            "model_name": "real_intake",
        }
        details = {k: v for k, v in details.items() if v not in (None, "", [])}
        details["habits"] = stable_habits(name, details)
        details["provenance"] = {
            "demographics": "real_intake: observed",
            "profile": "real_intake: customer_excerpts",
            "interview": "real_intake: verbatim_excerpts" if excerpts else "none",
            "bde": "real_intake: structured" if bde else "unobserved",
            "habits": "planner: seeded by identity",
        }
        profile = {
            "bio": str(r.get("bio") or f"{occupation}, {city or country}")[:280],
            "persona": persona_text,
            "age": age,
            "gender": gender,
            "mbti": str(r.get("mbti") or "ISTJ"),
            "country": country,
            "profession": occupation,
            "interested_topics": _str_list(r.get("interested_topics")),
        }
        out.append(
            EntityNode(
                uuid=f"persona_{idx:04d}",
                name=name,
                labels=["Entity", _type_name(r.get("entity_type") or "Person"), PERSONA_LABEL],
                summary=f"Grounded persona ({seg_label}): {name}, {age}, {gender}, {occupation}.",
                attributes={**details, SYNTHETIC_PROFILE_KEY: profile},
            )
        )
    return out


def _to_entity(seg: PersonaSegment, slot: Dict[str, Any], row: Dict[str, Any], taken: set, idx: int,
               model_provider: str = "", model_name: str = "") -> EntityNode:
    name = _dedupe_name(str(row.get("name") or f"{seg.label} {idx + 1}"), taken)
    country = str(row.get("country") or seg.country or "")
    city = str(row.get("city") or slot.get("city") or "")
    occupation = str(row.get("occupation") or seg.role or seg.label)
    persona = str(row.get("persona") or "").strip()
    traits = slot.get("traits") or {}
    details = {
        "segment": seg.label, "role": seg.role, "city": city, "country": country, "settlement": slot.get("settlement"),
        "life_stage": slot.get("life_stage"), "payday_status": slot.get("payday_status"),
        "occupation": occupation, "education": traits.get("education") or row.get("education"), "household": row.get("household"),
        "income_level": traits.get("income") or row.get("income_level"), "languages": row.get("languages") or seg.languages,
        "platform_habits": row.get("platform_habits"), "decision_role": row.get("decision_role"),
        "attitude": row.get("attitude"), "concerns": row.get("concerns"),
        "what_persuades_them": row.get("what_persuades_them"), "voice": row.get("voice"),
        "example_post": row.get("example_post"), "contradiction": row.get("contradiction"),
        "model_provider": model_provider or "claude", "model_name": model_name or "default",
        **traits,
    }
    details = {k: v for k, v in details.items() if v not in (None, "", [])}
    details["habits"] = stable_habits(name, details)
    synth_tag = f"synthetic: model-written ({model_provider}/{model_name})" if model_provider else "synthetic: model-written"
    details["provenance"] = {"demographics": "planner: coupled life-stage slot", "profile": synth_tag,
                             "interview": "none yet", "habits": "planner: seeded by identity"}
    if not persona:
        persona = f"{name}, {slot['age']}, {occupation} from {city or country}. " + " ".join(
            f"{k.replace('_', ' ')}: {v}." for k, v in details.items() if k not in ("city", "country"))
    else:
        extras = []
        if details.get("voice"):
            extras.append(f"Writes like this: {details['voice']}")
        if isinstance(details.get("concerns"), list):
            extras.append(f"Concerns: {', '.join(map(str, details['concerns']))}.")
        tr = slot.get("traits") or {}
        if tr:
            extras.append("Background: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in tr.items()) + ".")
        if details.get("contradiction"):
            extras.append(f"Contradiction: {details['contradiction']}")
        persona = " ".join([persona] + extras)
    profile = {
        "bio": str(row.get("bio") or f"{occupation}, {city or country}")[:280],
        "persona": persona,
        "age": int(slot["age"]),
        "gender": slot["gender"],
        "mbti": slot["mbti"],
        "country": country,
        "profession": occupation,
        "interested_topics": _str_list(row.get("interested_topics")),
    }
    summary = (f"Synthetic persona ({seg.label}): {name}, {slot['age']}, {slot['gender']}, {occupation}, "
               f"{city + ', ' if city else ''}{country}. {row.get('attitude') or ''}").strip()
    return EntityNode(
        uuid=f"persona_{idx:04d}",
        name=name,
        labels=["Entity", seg.entity_type, PERSONA_LABEL],
        summary=summary,
        attributes={**details, SYNTHETIC_PROFILE_KEY: profile},
    )


# --------------------------------------------------------------------------
# Communities: membership, group accounts and the in-group follow graph
# --------------------------------------------------------------------------

def _matches(comm: CommunitySpec, seg_label: str, country: str) -> bool:
    if comm.segments:
        return seg_label.lower() in {x.lower() for x in comm.segments}
    if comm.countries:
        return bool(country) and any(c.lower() in country.lower() or country.lower() in c.lower()
                                     for c in comm.countries)
    return True


def assign_communities(entities: List[EntityNode], spec: PersonaSpec, rng: random.Random) -> None:
    """Give each persona up to max_communities_per_person matching communities and fold in the norms."""
    for e in entities:
        if PERSONA_LABEL not in e.labels:
            continue
        attrs = e.attributes
        seg, country = str(attrs.get("segment") or ""), str(attrs.get("country") or "")
        options = [c for c in spec.communities if _matches(c, seg, country)]
        rng.shuffle(options)
        joined = [c for c in options if rng.random() < c.join_share][:spec.max_communities_per_person]
        attrs["communities"] = [c.name for c in joined]
        prof = attrs.get(SYNTHETIC_PROFILE_KEY)
        if joined and prof:
            lines = "; ".join(f"{c.name} ({c.kind})" + (f", where {c.norms}" if c.norms else "") for c in joined)
            prof["persona"] = (f"{prof['persona']} Member of: {lines}. Most of what they see and share comes "
                               f"from these groups, and they talk the way members there do.")


def community_accounts(spec: PersonaSpec, taken: set) -> List[EntityNode]:
    out = []
    for i, c in enumerate(spec.communities):
        if not c.account:
            continue
        countries = list(dict.fromkeys(
            list(c.countries) + [s.country for s in spec.segments if s.country and s.label in c.segments]))
        name = _dedupe_name(c.name, taken)
        persona = (f"The admin/page account of {c.name}, a {c.kind}. {c.description} "
                   f"Norms: {c.norms or 'not stated'}. Posts questions and updates for members, moderates, "
                   f"shares what members care about, and reacts to outside content the way the group would.")
        out.append(EntityNode(
            uuid=f"community_{i:03d}", name=name,
            labels=["Entity", "Community", COMMUNITY_LABEL],
            summary=f"Community account: {c.name} ({c.kind}). {c.description}".strip(),
            attributes={"community": c.name, "kind": c.kind, "communities": [c.name],
                        SYNTHETIC_PROFILE_KEY: {
                            "bio": (f"{c.kind}: {c.description}" if c.description else c.kind)[:280],
                            "persona": persona, "age": 30, "gender": "other", "mbti": "ESFJ",
                            "country": ", ".join(countries) or "International", "profession": f"{c.kind} admin",
                            "interested_topics": [c.name]}},
        ))
    return out


def build_community_config(entities: List[EntityNode], spec: PersonaSpec,
                           rng: Optional[random.Random] = None) -> Dict[str, Any]:
    """Map communities to final agent ids and build the follow edges to seed before round 1.

    `entities` must be in final agent order (agent id = index)."""
    rng = rng or random.Random(spec.seed + 1)
    members: Dict[str, List[int]] = {c.name: [] for c in spec.communities}
    accounts: Dict[str, int] = {}
    for idx, e in enumerate(entities):
        if COMMUNITY_LABEL in e.labels:
            accounts[e.attributes.get("community")] = idx
            continue
        for name in e.attributes.get("communities") or []:
            if name in members:
                members[name].append(idx)
    people = [i for i, e in enumerate(entities) if PERSONA_LABEL in e.labels]
    groups_of = {i: {n for n, ids in members.items() if i in ids} for i in people}
    follows = set()
    for name, ids in members.items():
        acc = accounts.get(name)
        for a in ids:
            if acc is not None:
                follows.add((a, acc))
            peers = [b for b in ids if b != a]
            for b in rng.sample(peers, min(spec.in_group_follows, len(peers))):
                follows.add((a, b))
    if spec.bridge_rate > 0:
        for a in people:
            outsiders = [b for b in people if b != a and not (groups_of[a] & groups_of[b])]
            if outsiders and rng.random() < spec.bridge_rate:
                follows.add((a, rng.choice(outsiders)))
    return {
        "communities": [{"name": c.name, "kind": c.kind, "description": c.description, "norms": c.norms,
                         "account_id": accounts.get(c.name), "member_ids": members.get(c.name, [])}
                        for c in spec.communities],
        "follows": [list(f) for f in sorted(follows)],
        "in_group_follows": spec.in_group_follows,
        "bridge_rate": spec.bridge_rate,
    }


def persona_index(entities: List[EntityNode]) -> List[Dict[str, Any]]:
    """Per-agent metadata (agent id = position) for marketing breakdowns by segment, country, community."""
    out = []
    for idx, e in enumerate(entities):
        attrs = e.attributes or {}
        prof = attrs.get(SYNTHETIC_PROFILE_KEY) or {}
        kind = "persona" if PERSONA_LABEL in e.labels else "community" if COMMUNITY_LABEL in e.labels else "graph"
        out.append({
            "agent_id": idx, "name": e.name, "kind": kind, "entity_type": e.get_entity_type(),
            "segment": attrs.get("segment"), "country": attrs.get("country") or prof.get("country"),
            "city": attrs.get("city"), "age": prof.get("age"), "gender": prof.get("gender"),
            "occupation": attrs.get("occupation"), "income_level": attrs.get("income_level"),
            "decision_role": attrs.get("decision_role"), "communities": attrs.get("communities") or [],
            "languages": attrs.get("languages") or [], "platform_habits": attrs.get("platform_habits"),
            "phone": attrs.get("phone"), "data_plan": attrs.get("data_plan"),
            "interview_summary": attrs.get("interview_summary"),
            "bde": attrs.get("bde"), "weight": attrs.get("weight", 1.0),
            "settlement": attrs.get("settlement"), "life_stage": attrs.get("life_stage"),
            "payday_status": attrs.get("payday_status"),
            "model_provider": attrs.get("model_provider"), "model_name": attrs.get("model_name"),
            "habits": attrs.get("habits"), "provenance": attrs.get("provenance"), "depth": attrs.get("depth"),
            **{k: attrs.get(k) for k in DEFAULT_DIVERSITY if attrs.get(k)},
        })
    return out

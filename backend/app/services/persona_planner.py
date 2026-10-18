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

import json
import random
import re
import threading
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
MAX_PER_CALL = 5                 # shorter calls: a retry costs less and segments finish sooner
MAX_TOTAL_PERSONAS = 2000
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

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PersonaSegment":
        if not isinstance(d, dict) or not str(d.get("label") or "").strip():
            raise ValueError("each persona segment needs a non-empty 'label'")
        age_min, age_max = _int(d.get("age_min"), 18), _int(d.get("age_max"), 65)
        if age_min > age_max:
            age_min, age_max = age_max, age_min
        return cls(
            label=str(d["label"]).strip(),
            count=max(1, min(_int(d.get("count"), 5), 500)),
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
    seed: int = 7

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
        spec = cls(
            segments=segs,
            communities=[CommunitySpec.from_dict(c) for c in (d.get("communities") or [])],
            auto=bool(d.get("auto", not segs)),
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
            seed=_int(d.get("seed"), 7),
        )
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


def demographic_slots(seg: PersonaSegment, rng: random.Random,
                      diversity: Optional[Dict[str, List[str]]] = None) -> List[Dict[str, Any]]:
    """Ages spread evenly over [age_min, age_max], genders by gender_mix, cities round-robin,
    and every diversity trait spread evenly (balanced, shuffled) across the segment."""
    n = seg.count
    span = seg.age_max - seg.age_min
    ages = [seg.age_min + round(span * (i + 0.5) / n) for i in range(n)]
    women = round(n * _female_share(seg.gender_mix))
    genders = ["female"] * women + ["male"] * (n - women)
    rng.shuffle(genders)
    rng.shuffle(ages)
    cities = seg.cities or [""]
    offset = rng.randrange(len(cities))
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
    return [{"age": ages[i], "gender": genders[i], "city": cities[(i + offset) % len(cities)],
             "mbti": rng.choice(MBTI), "initial": letters[i % len(letters)],
             "traits": {k: v[i] for k, v in spread.items() if v}} for i in range(n)]


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


def _llm_json(client, model: str, prompt: str, temperature: float = 0.8, max_tokens: int = 8000) -> Any:
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = create_chat_completion(
                client, model=model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                temperature=max(0.2, temperature - 0.2 * attempt), max_tokens=max_tokens,
            )
            return parse_json_block(extract_chat_completion_text(resp))
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
                    avoid_names: Sequence[str], communities: Sequence[CommunitySpec] = ()) -> str:
    people = "\n".join(
        f"{i + 1}. age {s['age']}, {s['gender']}" + (f", lives in {s['city']}" if s["city"] else "")
        + f", MBTI {s['mbti']}" + (f", given name starts with '{s['initial']}'" if s.get("initial") else "")
        + "".join(f"; {k.replace('_', ' ')}: {v}" for k, v in (s.get("traits") or {}).items())
        for i, s in enumerate(slots))
    groups = ""
    if communities:
        groups = "\nCommunities people in this segment may belong to:\n" + "\n".join(
            f"- {c.name} ({c.kind}): {c.description} Norms: {c.norms}" for c in communities) + "\n"
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

Use exactly these fixed demographics, in this order:
{people}

Rules:
- Invent a realistic full name for each person: given name and family name common for their country,
  region, religion mix and generation. Do not reuse or resemble these names: {", ".join(list(avoid_names)[-60:]) or "none"}.
- Never use a real, famous or public person's name or biography.
- Make them genuinely different: let the fixed traits (upbringing, education, income, thinking style,
  tech comfort, media diet) shape their goals, family situation, trust in ads, what they already know
  about the topic, and how they would react (some enthusiastic, some sceptical, some indifferent or busy).
- Give each person one believable contradiction (e.g. a price-hunter who splurges on one thing, a sceptic
  who trusts one particular source) so nobody reads like a stereotype.
- Write their voice the way they actually post: language mix, slang or formality, typical length.

Return JSON: {{"personas": [{{
  "name": "...", "age": N, "gender": "male|female", "city": "...", "country": "...",
  "occupation": "...", "education": "...", "household": "...", "income_level": "low|lower-middle|middle|upper-middle|high",
  "languages": ["..."], "platform_habits": "...", "decision_role": "...",
  "attitude": "...", "concerns": ["..."], "what_persuades_them": "...", "contradiction": "...", "voice": "...",
  "example_post": "...", "interested_topics": ["..."],
  "bio": "one-line social media bio",
  "persona": "a 150-250 word description combining all of the above and how they relate to the topic"
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


def _interview_prompt(people: List[Dict[str, Any]], context: str) -> str:
    cards = "\n".join(
        f"{i + 1}. {p['name']}: age {p.get('age')}, {p.get('gender')}, {p.get('occupation')}, "
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

People:
{cards}

Questions:
{qs}

Return JSON: {{"interviews": [{{"name": "<person name as given>",
  "answers": [{{"q": "Q1", "a": "..."}}, ... 12 answers ...],
  "phone": "phone model and age", "data_plan": "wifi at home / prepaid data / unlimited...",
  "summary": "120 words in the first person, in their own voice, summarising who they are, their money situation,
  how they decide on purchases and what they distrust"}}]}}"""


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


def _probe_prompt(people: List[Dict[str, Any]], answers_by_name: Dict[str, List[Dict[str, Any]]],
                  probes_by_name: Dict[str, List[str]], product_qs: List[str], context: str) -> str:
    blocks = []
    for p in people:
        qa = "\n".join(f"  {x['q']}: {x['a']}" for x in answers_by_name.get(p["name"], [])[:12])
        qs = probes_by_name.get(p["name"], []) + product_qs
        blocks.append(f"{p['name']} ({p.get('age')}, {p.get('occupation')}, {p.get('city') or ''} {p.get('country') or ''}):\n"
                      f"Earlier answers:\n{qa}\nNow answer:\n" + "\n".join(f"  P{i + 1}. {q}" for i, q in enumerate(qs)))
    return f"""Second part of a life interview with {len(people)} fictional people (market simulation). First answer the
follow-up questions as each person would, in their own voice and everyday language mix, 1-3 sentences, concrete
(amounts in local currency, names of apps and places). People are not fully consistent or rational: let habits,
mood and money pressure show. Then fill the structured card from EVERYTHING they said: the card describes this one
person, never their group; copy their own words where you can.

Context (what they will react to later):
{context[:1200]}

{chr(10).join(blocks)}

Return JSON: {{"people": [{{"name": "<name as given>", "probe_answers": [{{"q": "P1", "a": "..."}}, ...],
  "bde": {json.dumps(BDE_SCHEMA, ensure_ascii=False)}}}]}}"""


def clean_bde(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    for section, fields in BDE_SCHEMA.items():
        src = raw.get(section) if isinstance(raw.get(section), dict) else {}
        sec: Dict[str, Any] = {}
        for k, spec in fields.items():
            v = src.get(k)
            if isinstance(spec, list):
                sec[k] = [str(x).strip()[:120] for x in (v if isinstance(v, list) else [v] if v else []) if str(x).strip()][:5]
            else:
                sec[k] = str(v or "").strip()[:240]
        out[section] = sec
    return out if any(any(v for v in sec.values()) for sec in out.values()) else None


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


def run_interviews(client, model: str, entities: List[EntityNode], context: str,
                   progress: Optional[Callable[[int, int, str], None]] = None, parallel: int = 4,
                   product: Optional[Dict[str, Any]] = None, probes: bool = True) -> int:
    """Interview every synthetic persona in batches; attach answers, phone/data plan and a first-person summary.
    With probes=True a second call per batch asks adaptive follow-ups and product questions and extracts the
    structured BDE card (background / decision procedure / evaluation). Returns the number of people interviewed."""
    people = [e for e in entities if PERSONA_LABEL in e.labels]
    batches = [people[i:i + INTERVIEW_BATCH] for i in range(0, len(people), INTERVIEW_BATCH)]
    if not batches:
        return 0
    done = 0

    def card(e: EntityNode) -> Dict[str, Any]:
        a = e.attributes or {}
        prof = a.get(SYNTHETIC_PROFILE_KEY) or {}
        return {"name": e.name, "age": prof.get("age"), "gender": prof.get("gender"), "occupation": a.get("occupation"),
                "city": a.get("city"), "country": a.get("country"), "segment": a.get("segment"),
                "languages": a.get("languages"), "upbringing": a.get("upbringing"), "education": a.get("education"),
                "income_level": a.get("income_level"), "income": a.get("income"), "thinking_style": a.get("thinking_style"),
                "tech_comfort": a.get("tech_comfort"), "media_diet": a.get("media_diet"), "attitude": a.get("attitude")}

    def run(batch: List[EntityNode]):
        try:
            data = _llm_json(client, model, _interview_prompt([card(e) for e in batch], context),
                             temperature=0.9, max_tokens=6000)
            rows = data.get("interviews") if isinstance(data, dict) else data
            return batch, [r for r in (rows or []) if isinstance(r, dict)]
        except Exception as e:  # noqa: BLE001 - an uninterviewed batch keeps its shorter persona
            logger.warning(f"interview batch failed: {e}")
            return batch, []

    product_qs = product_questions(product)

    def run_probes(batch: List[EntityNode]):
        """Second call: adaptive follow-ups, product questions, BDE card."""
        cards = [card(e) for e in batch if e.attributes.get("interview")]
        if not cards:
            return batch, []
        answers_by_name = {e.name: e.attributes.get("interview") or [] for e in batch}
        probes_by_name = {e.name: choose_probes(e.attributes.get("interview") or []) for e in batch}
        try:
            data = _llm_json(client, model, _probe_prompt(cards, answers_by_name, probes_by_name, product_qs, context),
                             temperature=0.8, max_tokens=7000)
            rows = data.get("people") if isinstance(data, dict) else data
            return batch, [r for r in (rows or []) if isinstance(r, dict)]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"interview probes failed: {e}")
            return batch, []

    count = 0
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        for batch, rows in pool.map(run, batches):
            by_name = {str(r.get("name") or "").strip().lower(): r for r in rows}
            for k, e in enumerate(batch):
                r = by_name.get(e.name.strip().lower()) or (rows[k] if k < len(rows) else None)
                if not r:
                    continue
                answers = [{"q": str(x.get("q") or f"Q{i + 1}"), "a": str(x.get("a") or "").strip()}
                           for i, x in enumerate(r.get("answers") or []) if isinstance(x, dict)]
                summary = str(r.get("summary") or "").strip()
                e.attributes["interview"] = answers
                if summary:
                    e.attributes["interview_summary"] = summary[:1200]
                if r.get("phone"):
                    e.attributes["phone"] = str(r["phone"])[:120]
                if r.get("data_plan"):
                    e.attributes["data_plan"] = str(r["data_plan"])[:120]
                prof = e.attributes.get(SYNTHETIC_PROFILE_KEY)
                if prof and summary:
                    prof["persona"] = f"{prof['persona']} In their own words: {summary}"
                count += 1
            done += len(batch)
            if progress:
                progress(done, len(people), "interviews")
        if probes:
            done = 0
            for batch, rows in pool.map(run_probes, batches):
                by_name = {str(r.get("name") or "").strip().lower(): r for r in rows}
                for k, e in enumerate(batch):
                    r = by_name.get(e.name.strip().lower()) or (rows[k] if k < len(rows) else None)
                    if not r:
                        continue
                    pa = [{"q": str(x.get("q") or f"P{i + 1}"), "a": str(x.get("a") or "").strip()}
                          for i, x in enumerate(r.get("probe_answers") or []) if isinstance(x, dict)]
                    if pa:
                        e.attributes["interview"] = (e.attributes.get("interview") or []) + pa
                    bde = clean_bde(r.get("bde"))
                    if bde:
                        e.attributes["bde"] = bde
                        prof = e.attributes.get(SYNTHETIC_PROFILE_KEY)
                        if prof:
                            prof["persona"] = f"{prof['persona']} How I decide: {render_bde(bde, 500)}"
                done += len(batch)
                if progress:
                    progress(done, len(people), "follow-up probes")
    return count


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


def generate_personas(client, model: str, spec: PersonaSpec, requirement: str, context: str,
                      progress: Optional[Callable[[int, int, str], None]] = None,
                      parallel: int = 4, product: Optional[Dict[str, Any]] = None) -> List[EntityNode]:
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

    jobs = []
    for seg in spec.segments:
        slots = demographic_slots(seg, rng, spec.diversity)
        seg_comms = [c for c in spec.communities if _matches(c, seg.label, seg.country)]
        for start in range(0, len(slots), MAX_PER_CALL):
            jobs.append((seg, slots[start:start + MAX_PER_CALL], seg_comms))
    total = sum(len(j[1]) for j in jobs)

    taken: set = set()
    done = 0

    def run(job_idx: int):
        seg, slots, comms = jobs[job_idx]
        prompt = _persona_prompt(seg, slots, requirement, context, sorted(taken), comms)
        data = _llm_json(client, model, prompt)
        rows = data.get("personas") if isinstance(data, dict) else data
        return job_idx, [r for r in (rows or []) if isinstance(r, dict)]

    # Pipelined: as soon as every persona job of a segment has returned, that segment is checked for stereotypes
    # and its interviews start, while other segments are still being written (F-speed item 3).
    seg_jobs: Dict[str, int] = {}
    for seg, _, _ in jobs:
        seg_jobs[seg.label] = seg_jobs.get(seg.label, 0) + 1
    seg_entities: Dict[str, List[Tuple[int, List[EntityNode]]]] = {}
    by_job: Dict[int, List[EntityNode]] = {}
    interview_futures = []
    interview_done: Dict[str, int] = {}
    lock = threading.Lock()
    fixed_total = 0

    def interview_progress(label: str):
        def cb(d: int, t: int, what: str):
            with lock:
                interview_done[label] = d
                total_done = sum(interview_done.values())
            if progress:
                progress(total_done, total, what)
        return cb

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool, \
            ThreadPoolExecutor(max_workers=max(1, parallel)) as ipool:
        futures = [pool.submit(run, i) for i in range(len(jobs))]
        for fut in as_completed(futures):
            job_idx, rows = fut.result()
            seg, slots, _comms = jobs[job_idx]
            ents = [_to_entity(seg, slot, rows[k] if k < len(rows) else {}, taken, job_idx * MAX_PER_CALL + k)
                    for k, slot in enumerate(slots)]
            by_job[job_idx] = ents
            done += len(slots)
            if progress:
                progress(done, total, seg.label)
            seg_entities.setdefault(seg.label, []).append((job_idx, ents))
            if len(seg_entities[seg.label]) == seg_jobs[seg.label]:
                group = [e for _, es in sorted(seg_entities[seg.label], key=lambda x: x[0]) for e in es]
                fixed_total += fix_duplicates(group, rng)
                if spec.interview:
                    interview_futures.append(ipool.submit(
                        run_interviews, client, model, group, context, progress=interview_progress(seg.label),
                        parallel=max(2, parallel // 2), product=product, probes=spec.probes))
        interviewed = sum(f.result() for f in interview_futures)

    entities: List[EntityNode] = [e for job_idx in range(len(jobs)) for e in by_job.get(job_idx, [])]
    for i, e in enumerate(entities):                               # agent id = position: renumber the uuids in order
        e.uuid = f"persona_{i:04d}"
    report = diversity_report(entities)
    if fixed_total or report["flagged"]:
        logger.info(f"persona planner: stereotype guard changed {fixed_total} people; low-variety segments: {report['flagged'] or 'none'}")
    if spec.interview:
        logger.info(f"persona planner: interviewed {interviewed} people")
    if spec.population:
        logger.info(f"persona planner: population weights for {population_weights(entities, spec.population)} people")
    if spec.communities:
        assign_communities(entities, spec, rng)
        entities.extend(community_accounts(spec, taken))
    return entities


def _to_entity(seg: PersonaSegment, slot: Dict[str, Any], row: Dict[str, Any], taken: set, idx: int) -> EntityNode:
    name = _dedupe_name(str(row.get("name") or f"{seg.label} {idx + 1}"), taken)
    country = str(row.get("country") or seg.country or "")
    city = str(row.get("city") or slot.get("city") or "")
    occupation = str(row.get("occupation") or seg.role or seg.label)
    persona = str(row.get("persona") or "").strip()
    details = {
        "segment": seg.label, "role": seg.role, "city": city, "country": country,
        "occupation": occupation, "education": row.get("education"), "household": row.get("household"),
        "income_level": row.get("income_level"), "languages": row.get("languages") or seg.languages,
        "platform_habits": row.get("platform_habits"), "decision_role": row.get("decision_role"),
        "attitude": row.get("attitude"), "concerns": row.get("concerns"),
        "what_persuades_them": row.get("what_persuades_them"), "voice": row.get("voice"),
        "example_post": row.get("example_post"), "contradiction": row.get("contradiction"),
        **(slot.get("traits") or {}),
    }
    details = {k: v for k, v in details.items() if v not in (None, "", [])}
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
            **{k: attrs.get(k) for k in DEFAULT_DIVERSITY if attrs.get(k)},
        })
    return out

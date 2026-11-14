"""
Feed test: put ads into realistic social feeds and let every persona scroll.

Each persona gets one feed per platform (Facebook, Instagram, Reddit, TikTok,
LinkedIn, X): a handful of localized organic posts with one test creative
inserted as the platform shows ads ("Sponsored", "Promoted"). When a platform
has several creatives, each persona sees exactly one of them (balanced random
assignment), so creatives are compared like a split test.

For every item the persona reports what they did: scrolled past, stopped and
for how long, how much of a video they watched, reacted (platform reactions),
commented, shared/sent, saved, clicked, or hid the ad, plus a one-line thought.
Platform playbooks describe how people really behave on each app, including
the base rates that keep LLM personas from being unrealistically positive.

Outputs ads-manager style metrics per creative and per audience segment, the
comments in each persona's voice, and an ordered event log the dashboard
replays on a platform-styled mock of the post.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils.anthropic_native import CACHE_BREAK
from . import creative_vision
from . import emotion, say_do
from ..utils.logger import get_logger
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from .persona_planner import parse_json_block

logger = get_logger('mirofish.feed_test')

PLATFORMS: Dict[str, Dict[str, Any]] = {
    "facebook": {
        "label": "Facebook", "ad_tag": "Sponsored",
        "reactions": ["like", "love", "care", "haha", "wow", "sad", "angry"],
        "playbook": (
            "Facebook feed on a phone. People scroll fast; most ads get under a second. Typical ads stop "
            "roughly 1 in 5 people for 2+ seconds, get clicked by about 1 in 100, and get comments from far "
            "fewer. Comments under ads are often questions (price, is it real, where), tags of friends or "
            "family, or scepticism. People share useful things to family groups or send them on Messenger. "
            "Friends' and family posts and group posts get most attention. Hiding an ad ('not interested') "
            "is common when it feels irrelevant or spammy."),
    },
    "instagram": {
        "label": "Instagram", "ad_tag": "Sponsored",
        "reactions": ["like"],
        "playbook": (
            "Instagram feed and Reels. Visual first: the first image or first second of video decides whether "
            "they stop. Likes are cheap and quick; comments on ads are rare and short (emojis, '@friend look'). "
            "Useful content gets saved; things for friends get sent by DM. Text-heavy or obviously salesy ads "
            "get swiped past. Typical ads stop about 1 in 4 people and get clicked by 1 to 2 in 100."),
    },
    "reddit": {
        "label": "Reddit", "ad_tag": "Promoted",
        "reactions": ["upvote", "downvote"],
        "playbook": (
            "Reddit, browsing subreddits that match their interests. Redditors dislike ads and marketing "
            "speak; promoted posts are often ignored or downvoted, and comments on them tend to be sceptical, "
            "sarcastic or asking for proof. Honest, specific, useful posts can still earn upvotes. Clicks on "
            "promoted posts are rare (well under 1 in 100) unless the offer is genuinely useful."),
    },
    "tiktok": {
        "label": "TikTok", "ad_tag": "Sponsored",
        "reactions": ["like"],
        "playbook": (
            "TikTok For You feed, full-screen vertical videos. The first 1-2 seconds decide whether they swipe. "
            "Most ads are swiped within 2 seconds; watch-through is low unless it feels like native content "
            "from a real creator. Likes are quick; comments are short and playful or questions; saves for "
            "tips; shares to friends."),
    },
    "linkedin": {
        "label": "LinkedIn", "ad_tag": "Promoted",
        "reactions": ["like", "celebrate", "support", "love", "insightful", "funny"],
        "playbook": (
            "LinkedIn feed at work. Professional framing; people engage with career, business and expert "
            "content. Ads with clear professional value get some clicks; consumer-style hype is ignored. "
            "Comments are rare and polite."),
    },
    "x": {
        "label": "X", "ad_tag": "Ad",
        "reactions": ["like"],
        "playbook": (
            "X (Twitter) timeline. Very fast scrolling, news and opinions. Ads are mostly ignored; replies "
            "can be blunt or mocking; reposts happen for funny or controversial content."),
    },
}

SYSTEM_PROMPT = (
    "You role-play one specific, fictional person scrolling social media on their phone. Stay in character: "
    "their age, country, language, money, mood and what they care about. Behave like real users, not like a "
    "focus group: most posts, and especially most ads, get scrolled past in under a second without any "
    "action. Only stop, react, comment or click when this person genuinely would. Comments are written the "
    "way this person types on that app. Return only valid JSON."
)

ORGANIC_SYSTEM = (
    "You write realistic, fictional social media feed posts for a simulation. Authors are invented people, "
    "local pages, groups and creators; never real or famous people. Mix everyday life, local news, jokes, "
    "groups and creators the way a real feed does. Return only valid JSON."
)

FALLBACK_ORGANIC = [
    {"kind": "friend", "author": "A friend", "text": "Finally finished exams, beach this weekend!", "media": "group selfie at the beach"},
    {"kind": "page", "author": "Local News", "text": "Traffic diversion on the main road from Monday.", "media": "map screenshot"},
    {"kind": "meme", "author": "Daily Memes", "text": "Me opening my banking app after the weekend", "media": "meme image"},
    {"kind": "group", "author": "Neighbourhood Group", "text": "Anyone know a good tailor nearby?", "media": ""},
    {"kind": "creator", "author": "Food Creator", "text": "3 street foods you must try this month", "media": "short video of food stalls"},
    {"kind": "friend", "author": "Cousin", "text": "Happy birthday to the best little brother!", "media": "birthday photo"},
    {"kind": "page", "author": "Sports Daily", "text": "What a finish last night!", "media": "match highlight video"},
    {"kind": "creator", "author": "Study Tips", "text": "How I revise 3x faster", "media": "talking-head video"},
]


# Connection speed multipliers on the page's 4G load time, and how they skew with income.
NETWORKS = {"wifi": 0.6, "4g": 1.0, "slow 4g": 1.8, "3g": 3.0}
NETWORK_WEIGHTS = {  # income -> weights for wifi, 4g, slow 4g, 3g
    "low": (0.10, 0.30, 0.35, 0.25), "lower-middle": (0.20, 0.40, 0.28, 0.12), "middle": (0.35, 0.45, 0.15, 0.05),
    "upper-middle": (0.50, 0.42, 0.06, 0.02), "high": (0.60, 0.37, 0.03, 0.0),
}

LANDING_SYSTEM = (
    "You role-play one specific, fictional person who just tapped an ad on their phone. Stay in character. "
    "Real people abandon pages that are slow, confusing, in a language they are not comfortable reading, or "
    "that ask for more than they want to give. Return only valid JSON."
)


def normalize_landing(raw: Any) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("landing must be an object")
    try:
        load = float(raw.get("load_seconds", 3))
    except (TypeError, ValueError):
        raise ValueError("landing.load_seconds must be a number")
    return {"load_seconds": max(0.3, min(load, 60.0)),
            "language": str(raw.get("language") or "English"),
            "shows": str(raw.get("shows") or raw.get("description") or "")[:800],
            "form_fields": [str(x) for x in (raw.get("form_fields") or [])][:12],
            "price": str(raw.get("price") or "free"),
            "steps": max(1, min(int(raw.get("steps") or 1), 10))}


def normalize_competitor(raw: Any) -> Optional[Dict[str, Any]]:
    """Normalize an optional competitor counter-offer / price-shock ad shown in the same feed."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("competitor must be an object")
    name = str(raw.get("name") or raw.get("page") or raw.get("brand") or "Competitor").strip()
    headline = str(raw.get("headline") or raw.get("title") or "").strip()
    text = str(raw.get("text") or raw.get("offer") or headline).strip()
    if not text and not headline:
        raise ValueError("competitor needs text, offer, or headline")
    return {
        "id": str(raw.get("id") or "comp1"),
        "name": name,
        "page": name,
        "headline": headline,
        "text": text,
        "price": str(raw.get("price") or "").strip(),
        "cta": str(raw.get("cta") or "Learn more").strip(),
        "format": str(raw.get("format") or "image").strip().lower(),
        "media": str(raw.get("media") or "").strip(),
    }


def check_say_do_friction(person: Dict[str, Any], landing: Dict[str, Any], rng: random.Random,
                          fx: Optional[Dict[str, float]] = None) -> Optional[Tuple[str, str]]:
    """The research-backed Say-vs-Do gate for a clicker on the landing page (wallet limit, dealbreakers, polite
    yes-sayers backing out at payment); the rules live in say_do.friction, shared with the survey and pitch split."""
    return say_do.friction(person, landing, rng, fx)


def network_for(person: Dict[str, Any], rng: random.Random) -> str:
    w = NETWORK_WEIGHTS.get(str(person.get("income") or "middle").lower(), NETWORK_WEIGHTS["middle"])
    return rng.choices(list(NETWORKS), weights=w)[0]


def patience_for(person: Dict[str, Any], rng: random.Random) -> float:
    """Seconds this person will wait for a page. Most mobile users leave after a few seconds."""
    style = str(person.get("thinking_style") or "").lower()
    base = rng.uniform(2.0, 8.0)
    if "busy" in style or "distracted" in style:
        base *= 0.6
    if "analytical" in style or "price-hunter" in style:
        base *= 1.3
    return round(base, 1)


FEEL_HINT = ("Most ads make people feel nothing much, so \"neutral\" with low intensity is the normal answer; only name a "
             "feeling you would really have. pleasant -1..1, fair -1 (feels manipulative) to 1 (feels honest), the rest 0..1.")
FEEL_JSON = ('"feel": {"emotion": "neutral|interest|joy|trust|surprise|fomo|irritation|anxiety|sadness|disgust|regret|pressured", "intensity": 0.0, "pleasant": 0.0, "novel": 0.0, "relevant": 0.0, "control": 0.0, "fair": 0.0, "urgent": 0.0, "words": "how it made you feel, under 10 words"}')


def landing_prompt(person: Dict[str, Any], creative: Dict[str, Any], landing: Dict[str, Any], waited: float,
                   feel: bool = False) -> str:
    fields = ", ".join(landing["form_fields"]) or "no form"
    if feel:
        return (
            f"Who you are:\n{person['persona'][:1200]}\n\nYou tapped this ad: \"{creative.get('headline') or creative['text'][:120]}\" "
            f"from {creative['page']}. The page took {waited:.1f} seconds to load on your phone.\n"
            f"The page is in {landing['language']}. It shows: {landing['shows'] or 'the offer from the ad'}.\n"
            f"Price: {landing['price']}. To finish you must fill in: {fields} ({landing['steps']} step(s)).\n\n"
            "Do you actually read it, start filling the form, and finish? Be honest about what would stop you. "
            "Also say how the page made you feel. " + FEEL_HINT + "\n"
            'Return JSON: {"read": true, "started_form": false, "completed": false, '
            '"drop_reason": "why you left, or empty", "thought": "under 15 words", ' + FEEL_JSON + '}'
        )
    return (
        f"Who you are:\n{person['persona'][:1200]}\n\nYou tapped this ad: \"{creative.get('headline') or creative['text'][:120]}\" "
        f"from {creative['page']}. The page took {waited:.1f} seconds to load on your phone.\n"
        f"The page is in {landing['language']}. It shows: {landing['shows'] or 'the offer from the ad'}.\n"
        f"Price: {landing['price']}. To finish you must fill in: {fields} ({landing['steps']} step(s)).\n\n"
        "Do you actually read it, start filling the form, and finish? Be honest about what would stop you.\n"
        'Return JSON: {"read": true, "started_form": false, "completed": false, '
        '"drop_reason": "why you left, or empty", "thought": "under 15 words"}'
    )


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

MAX_IMAGE_CHARS = 5_600_000      # a 4 MB image as base64


def _visual_sources(c: Dict[str, Any], i: int) -> Dict[str, Any]:
    """The creative's image (data URI or https URL) and video keyframes, when given."""
    out: Dict[str, Any] = {}
    img = c.get("image")
    if isinstance(img, str) and img.strip():
        img = img.strip()
        if not (img.startswith("data:image/") or img.startswith("https://")):
            raise ValueError(f"creative {i + 1}: image must be a data:image/... URI or an https URL "
                             "(the CLI turns a local file into a data URI)")
        if len(img) > MAX_IMAGE_CHARS:
            raise ValueError(f"creative {i + 1}: image is larger than 4 MB")
        out["image"] = img
    frames = [f.strip() for f in (c.get("frames") or []) if isinstance(f, str) and f.strip()]
    if frames:
        if any(not f.startswith("data:image/") or len(f) > MAX_IMAGE_CHARS for f in frames):
            raise ValueError(f"creative {i + 1}: frames must be data:image/... URIs under 4 MB each")
        out["frames"] = frames[:4]
    return out


def normalize_creatives(raw: Any) -> List[Dict[str, Any]]:
    """Validate the creatives list; returns cleaned dicts with ids."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("creatives must be a non-empty list")
    out = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            raise ValueError(f"creative {i + 1} must be an object")
        platform = str(c.get("platform") or "facebook").strip().lower()
        if platform == "twitter":
            platform = "x"
        if platform not in PLATFORMS:
            raise ValueError(f"creative {i + 1}: unknown platform '{platform}' (use {', '.join(PLATFORMS)})")
        text = str(c.get("text") or c.get("primary_text") or c.get("body") or "").strip()
        headline = str(c.get("headline") or c.get("title") or "").strip()
        if not text and not headline:
            raise ValueError(f"creative {i + 1}: needs text or headline")
        out.append({
            "id": str(c.get("id") or f"ad{i + 1}"),
            "name": str(c.get("name") or headline or text[:40]),
            "platform": platform,
            "format": str(c.get("format") or "image").strip().lower(),
            "page": str(c.get("page") or c.get("advertiser") or "Brand").strip(),
            "text": text, "headline": headline,
            "cta": str(c.get("cta") or "").strip(),
            "media": str(c.get("media") or c.get("media_description") or "").strip(),
            "link": str(c.get("link") or "").strip(),
            "segments": [str(x) for x in (c.get("segments") or [])],
            "countries": [str(x) for x in (c.get("countries") or [])],
            **_visual_sources(c, i),
        })
    ids = [c["id"] for c in out]
    if len(set(ids)) != len(ids):
        raise ValueError("creative ids must be unique")
    return out


def people_from_simulation(profiles: List[Dict[str, Any]], persona_index: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge profile text with persona metadata; keep only individual people."""
    meta = {int(r["agent_id"]): r for r in persona_index or [] if isinstance(r, dict) and r.get("agent_id") is not None}
    people = []
    for i, p in enumerate(profiles or []):
        aid = int(p.get("user_id", i)) if str(p.get("user_id", i)).isdigit() else i
        m = meta.get(aid, {})
        kind = m.get("kind") or ("graph" if str(p.get("gender") or "").lower() == "other" else "person")
        if kind not in ("persona", "person"):
            continue
        people.append({"agent_id": aid, "name": p.get("name") or m.get("name") or f"agent {aid}",
                       "persona": str(p.get("persona") or p.get("user_char") or p.get("bio") or "")[:1800],
                       "age": p.get("age") or m.get("age"), "gender": p.get("gender") or m.get("gender"),
                       "country": p.get("country") or m.get("country") or "",
                       "segment": m.get("segment") or p.get("profession") or "Everyone",
                       "communities": m.get("communities") or [], "income": m.get("income") or m.get("income_level"),
                       "thinking_style": m.get("thinking_style"), "tech_comfort": m.get("tech_comfort"),
                       "habits": m.get("habits"), "settlement": m.get("settlement"),
                       "life_stage": m.get("life_stage"), "payday_status": m.get("payday_status"),
                       "model_provider": m.get("model_provider"), "model_name": m.get("model_name"),
                       "provenance": m.get("provenance"),
                       "bde": m.get("bde"), "memory": m.get("memory")})
    if any(m.get("kind") == "persona" for m in meta.values()):
        people = [x for x in people if meta.get(x["agent_id"], {}).get("kind") == "persona"]
    return people


def _words(s: Any) -> set:
    return {w for w in re.findall(r"[a-z]+", str(s or "").lower()) if len(w) > 2 and w not in ("the", "and", "all", "metro", "cities", "city")}


def segment_matches(wanted: str, segment: str) -> bool:
    """Exact label, or a loose match: every content word of the wanted label appears in the person's segment
    ("India parents" matches "Working parents, India, metro cities"; singular/plural tolerated)."""
    if not wanted or not segment:
        return False
    if wanted.strip().lower() == segment.strip().lower():
        return True
    have = _words(segment)
    stems = {w.rstrip("s") for w in have}
    return all(w in have or w.rstrip("s") in stems for w in _words(wanted))


def targets(creative: Dict[str, Any], person: Dict[str, Any]) -> bool:
    if creative["segments"] and not any(segment_matches(w, person["segment"]) for w in creative["segments"]):
        return False
    if creative["countries"]:
        c = str(person.get("country") or "").lower()
        return any(x.lower() in c or c in x.lower() for x in creative["countries"]) if c else False
    return True


def assign(creatives: List[Dict[str, Any]], people: List[Dict[str, Any]], seed: int = 5) -> Dict[Tuple[int, str], Dict[str, Any]]:
    """(agent_id, platform) -> the one creative this person sees on that platform (balanced per platform)."""
    rng = random.Random(seed)
    plan: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for platform in sorted({c["platform"] for c in creatives}):
        pcs = [c for c in creatives if c["platform"] == platform]
        load = Counter()
        order = list(people)
        rng.shuffle(order)
        for person in order:
            eligible = [c for c in pcs if targets(c, person)]
            if not eligible:
                continue
            least = min(load[c["id"]] for c in eligible)
            choice = rng.choice([c for c in eligible if load[c["id"]] == least])
            load[choice["id"]] += 1
            plan[(person["agent_id"], platform)] = choice
    return plan


# --------------------------------------------------------------------------
# LLM calls
# --------------------------------------------------------------------------

class UsageMeter:
    """Wraps an OpenAI-style client and counts calls and tokens, so every run reports what it cost."""

    def __init__(self, client):
        self._client = client
        self._lock = threading.Lock()
        self.calls = self.input_tokens = self.output_tokens = 0
        self.usage_sources = set()
        self.by_provider: Dict[str, Dict[str, int]] = {}      # provider that answered -> calls / tokens
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def __getattr__(self, name):            # base_url etc. for is_claude_target
        if name in ("for_agent", "for_slot") and hasattr(self._client, name):
            def _bound_proxy(key):
                sub = getattr(self._client, name)(key)
                return SimpleNamespace(
                    chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: self._create_on(sub, **kw))),
                    base_url=getattr(sub, "base_url", getattr(self._client, "base_url", "")),
                    provider=getattr(sub, "provider", None),
                    model_name=getattr(sub, "model_name", None),
                )
            return _bound_proxy
        return getattr(self._client, name)

    def _create_on(self, target, **kw):
        resp = target.chat.completions.create(**kw)
        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        prov = response_provider(resp, target, kw.get("model"))
        with self._lock:
            self.calls += 1
            self.input_tokens += in_tok
            self.output_tokens += out_tok
            self.usage_sources.add(getattr(resp, "usage_source", None) or ("provider" if usage else "unavailable"))
            row = self.by_provider.setdefault(prov, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            row["calls"] += 1
            row["input_tokens"] += in_tok
            row["output_tokens"] += out_tok
        return resp

    def _create(self, **kw):
        return self._create_on(self._client, **kw)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    def provider_snapshot(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            return {k: dict(v) for k, v in self.by_provider.items()}


def provider_diff(end: Dict[str, Dict[str, int]], start: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    out = {}
    for prov, row in end.items():
        base = start.get(prov) or {}
        d = {k: int(v) - int(base.get(k, 0)) for k, v in row.items()}
        if d.get("calls"):
            out[prov] = d
    return out


def add_provider_usage(*parts: Optional[Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for part in parts:
        for prov, row in (part or {}).items():
            acc = out.setdefault(prov, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            for k, v in row.items():
                acc[k] = acc.get(k, 0) + int(v or 0)
    return out


def client_provider(client: Any, model: Optional[str] = None) -> str:
    """Provider label of a client (pool slot view, gateway or hosted API) when no response says otherwise."""
    from ..utils.model_pool import canonical_provider
    prov = getattr(client, "provider", None)
    if isinstance(prov, str) and prov:
        return prov
    return canonical_provider(None, str(getattr(client, "base_url", "") or ""), model)


def assigned_provider(client: Any, agent_id: Any, model: Optional[str] = None) -> str:
    """The provider a person is routed to (pool slot via for_agent), for sessions that made no model call."""
    if hasattr(client, "for_agent"):
        try:
            return client_provider(client.for_agent(agent_id), model)
        except Exception:  # noqa: BLE001 - fall back to the client's own label
            pass
    return client_provider(client, model)


def response_provider(resp: Any, client: Any = None, model: Optional[str] = None) -> str:
    """The provider that produced `resp`: the pool's record (after any failover), else the backend a gateway
    reports in the response, else the client's own label."""
    from ..utils.model_pool import answered_provider
    prov = getattr(resp, "_mm_provider", None)
    if isinstance(prov, str) and prov:
        return prov
    return answered_provider(resp) or client_provider(client, model)


def _llm_json(
    client,
    model: str,
    system: str,
    prompt: str,
    temperature: float = 0.8,
    max_tokens: int = 3000,
    agent_id: Optional[Any] = None,
    return_meta: bool = False,
    images: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    last: Optional[Exception] = None
    user: Any = prompt
    if images:      # shared part + the ad's picture (cached together), then the per-person part
        shared, mark, rest = prompt.partition(CACHE_BREAK)
        user = ([{"type": "text", "text": shared + "\n\nThe Sponsored/Promoted item's picture (what it looks like in "
                                                     "your feed) is attached here."}] + list(images)
                + [{"type": "text", "text": (CACHE_BREAK + rest) if mark else ""}])
    for attempt in range(3):
        try:
            call_kw: Dict[str, Any] = {
                "model": model,
                "temperature": max(0.3, temperature - 0.2 * attempt),
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
            if agent_id is not None:
                call_kw["agent_id"] = agent_id
            resp = create_chat_completion(client, **call_kw)
            parsed = parse_json_block(extract_chat_completion_text(resp))
            if return_meta:
                prov = response_provider(resp, client, model)
                mod = getattr(resp, "_mm_model", None) or getattr(resp, "model", None) or model
                mod = mod if isinstance(mod, str) else model
                return parsed, str(prov), str(mod)
            return parsed
        except Exception as e:  # noqa: BLE001 - retried then raised
            last = e
            logger.warning(f"feed test LLM call failed (attempt {attempt + 1}): {str(e)[:120]}")
    raise RuntimeError(f"feed test LLM call failed: {last}")


def organic_pool(client, model: str, platform: str, country: str, context: str, n: int = 10,
                 voices: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    label = PLATFORMS[platform]["label"]
    real = ""
    if voices:
        from .research import pick_voices
        picks = pick_voices(voices, 3, country)
        if picks:
            real = "Real things people posted about this kind of product (use the tone and concerns, not the words):\n" + \
                   "\n".join(f"- {v['text'][:200]}" for v in picks) + "\n"
    prompt = (f"Write {n} varied {label} feed posts that a typical person in {country or 'this audience'} would see "
              f"today, in the languages people there actually post in. Some background on the audience:\n"
              f"{context[:1500]}\n{real}\nReturn JSON: {{\"posts\": [{{\"kind\": \"friend|family|group|page|creator|news|meme\", "
              f"\"author\": \"invented name or page\", \"text\": \"post text\", \"media\": \"what the photo/video shows, or empty\"}}]}}")
    try:
        data = _llm_json(client, model, ORGANIC_SYSTEM, prompt, temperature=0.9, max_tokens=2500)
        posts = [p for p in (data.get("posts") if isinstance(data, dict) else data) or [] if isinstance(p, dict) and p.get("text")]
        if len(posts) >= 4:
            return posts
    except Exception as e:  # noqa: BLE001 - fall back to generic posts
        logger.warning(f"organic posts for {platform}/{country} failed, using fallback: {e}")
    return list(FALLBACK_ORGANIC)


_POOL_LOCK = threading.Lock()
SEED_WORKERS = max(1, int(os.environ.get("FEED_TEST_SEED_WORKERS", "4") or 4))


def organic_pools(client, model: str, keys: List[Tuple[str, str]], context: str, parallel: int = 8,
                  pools: Optional[Dict[Tuple[str, str], List[Dict[str, Any]]]] = None,
                  voices: Optional[List[Dict[str, Any]]] = None) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Fill `pools` with an organic pool per missing (platform, country) key, all in parallel. The dict is
    shared between the seeds of one run_multi_seed, so each pool is generated once per run."""
    pools = pools if pools is not None else {}
    with _POOL_LOCK:
        missing = sorted({k for k in keys if k not in pools})
    if not missing:
        return pools
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(missing)))) as ex:
        built = list(ex.map(lambda k: (k, organic_pool(client, model, k[0], k[1], context, voices=voices)), missing))
    with _POOL_LOCK:
        for k, pool in built:
            pools.setdefault(k, pool)
    return pools


def _plan(creatives: List[Dict[str, Any]], people: List[Dict[str, Any]], seed: int):
    """(creatives, plan) for one seed; falls back to untargeted creatives when the labels match nobody."""
    plan = assign(creatives, people, seed)
    if not plan:
        # the creatives' segment labels match nobody (e.g. a spec from another run): show every ad to everyone
        logger.warning("feed test: no persona matches the creatives' targeting; ignoring segment/country targeting")
        creatives = [{**c, "segments": [], "countries": []} for c in creatives]
        plan = assign(creatives, people, seed)
        if not plan:
            raise ValueError("no persona matches the creatives' targeting")
    return creatives, plan


def render_item(item_id: str, post: Dict[str, Any], platform: str, is_ad: bool,
                proof: Optional[Dict[str, Any]] = None) -> str:
    if is_ad:
        tag = PLATFORMS[platform]["ad_tag"]
        bits = [f"[{item_id}] {post['page']} · {tag}", post["text"]]
        if proof and (proof["reactions"] or proof.get("comment_count") or proof["shares"]):
            bits.append(f"({proof['reactions']} reactions · {proof.get('comment_count', len(proof['comments']))} comments"
                        f" · {proof['shares']} shares)")
            if proof["comments"]:
                bits.append("You opened the comments:")
                bits += [f'  {c["first"]}: "{c["text"]}"' for c in proof["comments"][-2:]]
        if proof and proof.get("seen_before"):
            bits.append(f"(You have scrolled past this same ad {proof['seen_before']} time(s) before.)")
        if post.get("media"):
            bits.append(f"({post['format']}: {post['media']})")
        if post.get("headline"):
            bits.append(f"Headline: {post['headline']}")
        if post.get("cta"):
            bits.append(f"Button: [{post['cta']}]")
        return "\n".join(b for b in bits if b)
    bits = [f"[{item_id}] {post.get('author', 'Someone')} ({post.get('kind', 'post')})", str(post.get("text", ""))]
    if post.get("media"):
        bits.append(f"(media: {post['media']})")
    return "\n".join(bits)


def scroll_prompt(person: Dict[str, Any], platform: str, feed: List[str], hour: int,
                  habits: Optional[Dict[str, Any]] = None, feel: bool = False) -> str:
    pb = PLATFORMS[platform]
    reactions = "|".join(["none"] + pb["reactions"])
    h = habits or {}
    facts = ""
    if h:
        facts = (f"Your habits (facts, not suggestions): you ignore most ads (ad avoidance {h['ad_avoidance']} on a 0-1 scale); "
                 f"you comment on posts {h['comments']}; you {h['clicks_ads']} click on ads; you share things {h['shares']}. "
                 "You do not know typical prices or what other products cost unless the post says so.\n")
    # shared by everyone on this platform first (cached on Claude's native API), the person and their feed after
    return (
        f"You are scrolling {pb['label']} on your phone.\nHow people behave here: {pb['playbook']}\n\n"
        "For EVERY item in your feed say what you actually do. Your options, most common first: scroll past, glance, "
        "stop and read, react, comment, share, click. Most items should be a quick scroll past with no action.\n"
        "For the Sponsored/Promoted item also give your honest probabilities (0-1) of each action if you saw it on a "
        "normal day: p_click, p_react, p_comment, p_share, p_hide.\n"
        + ("For the Sponsored/Promoted item also add \"feel\": how the ad made you feel. " + FEEL_HINT + "\n" if feel else "")
        + "Return JSON: {\"items\": [{\"id\": \"i1\", \"stopped\": false, \"dwell_seconds\": 0.5, \"watched_pct\": 0, "
        f"\"reaction\": \"{reactions}\", \"comment\": \"what you type, or empty\", \"share\": \"none|share|send\", "
        "\"save\": false, \"click\": false, \"hide\": false, \"thought\": \"your honest inner reaction in under 15 words\", "
        "\"p_click\": 0.0, \"p_react\": 0.0, \"p_comment\": 0.0, \"p_share\": 0.0, \"p_hide\": 0.0"
        + (", " + FEEL_JSON + " (Sponsored/Promoted item only)" if feel else "") + "}]}"
        + CACHE_BREAK
        + f"Who you are:\n{person['persona']}\n(Age {person.get('age')}, {person.get('gender')}, {person.get('country')}.)\n{facts}\n"
        + (f"{person['history']}\n" if person.get("history") else "")
        + f"It is {hour}:00.\n\nYour feed, top to bottom:\n\n" + "\n\n".join(feed)
    )


# --------------------------------------------------------------------------
# Run + aggregate
# --------------------------------------------------------------------------

def _num(v: Any, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def normalize_action(d: Dict[str, Any], platform: str) -> Dict[str, Any]:
    reaction = str(d.get("reaction") or "none").strip().lower()
    if reaction not in PLATFORMS[platform]["reactions"]:
        reaction = "none"
    share = str(d.get("share") or "none").strip().lower()
    share = share if share in ("share", "send") else "none"
    dwell = _num(d.get("dwell_seconds"), 0, 120)
    stopped = bool(d.get("stopped")) or dwell >= 1.5
    comment = str(d.get("comment") or "").strip()
    if comment.lower() in ("none", "null", "n/a", "-", "no comment"):
        comment = ""
    out = {"stopped": stopped, "dwell": round(dwell, 1), "watched_pct": round(_num(d.get("watched_pct"), 0, 100)),
           "reaction": reaction, "comment": comment[:400], "share": share, "save": bool(d.get("save")),
           "click": bool(d.get("click")), "hide": bool(d.get("hide")), "thought": str(d.get("thought") or "")[:200]}
    # stated probabilities (smoother than one yes/no draw); fall back to what they did
    for key, did in (("p_click", out["click"]), ("p_react", reaction != "none"), ("p_comment", bool(comment)),
                     ("p_share", share != "none"), ("p_hide", out["hide"])):
        v = d.get(key)
        out[key] = round(_num(v, 0, 1), 3) if v is not None else (1.0 if did else 0.0)
    feel = emotion.normalize_feel(d.get("feel"))
    if feel:
        out["feel"] = feel
    return out


# Realism controls (see README "How realistic is it?"):
# chance an ad catches the eye at all on each platform, before any LLM call
NOTICE_RATE = {"facebook": 0.30, "instagram": 0.35, "reddit": 0.25, "tiktok": 0.40, "linkedin": 0.30, "x": 0.25}
COMMENT_OPEN_RATE = 0.35        # share of viewers who open the comments under an ad
WEAR_OUT = 0.8                   # each repeat exposure multiplies the notice chance by this


def person_habits(person: Dict[str, Any]) -> Dict[str, Any]:
    """Stable habits: from the persona (seeded by identity at planning time), else derived from the name, never
    from the experiment seed, so a person behaves alike across seeds, scenarios and test types."""
    h = person.get("habits")
    if isinstance(h, dict) and h.get("ad_avoidance") is not None:
        return h
    from .persona_planner import identity_seed
    return behaviour_traits(person, random.Random(identity_seed(str(person.get("name") or person.get("agent_id")))))


def behaviour_traits(person: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    """Skewed, per-person habits stated to the persona as facts (not adjectives)."""
    style = str(person.get("thinking_style") or "").lower()
    avoid = rng.betavariate(2.2, 1.8)
    if "sceptical" in style or "risk-averse" in style or "traditional" in style:
        avoid = min(1.0, avoid + 0.15)
    if "early adopter" in style or "status" in style:
        avoid = max(0.0, avoid - 0.2)
    return {"ad_avoidance": round(avoid, 2),
            "comments": rng.choices(["a few times a week", "about once a week", "about once a month",
                                     "a few times a year", "almost never"], [0.07, 0.15, 0.28, 0.3, 0.2])[0],
            "clicks_ads": rng.choices(["almost never", "rarely", "sometimes"], [0.45, 0.4, 0.15])[0],
            "shares": rng.choices(["often", "sometimes", "rarely"], [0.15, 0.4, 0.45])[0]}


def run_feed_test(client, model: str, creatives: List[Dict[str, Any]], people: List[Dict[str, Any]],
                  context: str = "", organic_per_feed: int = 5, parallel: int = 8, seed: int = 5,
                  progress: Optional[Callable[[int, int], None]] = None, waves: int = 3,
                  landing: Optional[Dict[str, Any]] = None, benchmarks: Optional[Dict[str, Any]] = None,
                  exposures: int = 2, attention_gate: bool = True,
                  pools: Optional[Dict[Tuple[str, str], List[Dict[str, Any]]]] = None,
                  voices: Optional[List[Dict[str, Any]]] = None,
                  competitor: Optional[Dict[str, Any]] = None,
                  include_generic_baseline: bool = False, vision: str = "describe",
                  emotions: Optional[str] = None) -> Dict[str, Any]:
    """vision: "direct" also sends each creative's image with every scroll call (the image sits in the cached shared
    part); "describe" / "off" leave the scroll calls text-only (describe runs once per creative before the test).
    waves: later waves see earlier reaction counts (and, if they open them, comments).
    exposures: how many times each person scrolls past the ad (frequency, with wear-out).
    attention_gate: decide in code whether the ad is noticed at all; unnoticed ads are a quick scroll past.
    landing: optional page model; clickers face load time on their network, then decide to finish or leave.
    benchmarks: optional {platform: {cpm, ctr, budget, currency, lead_value, ...}} for projections.
    pools: organic posts per (platform, country), shared across seeds; missing keys are generated in parallel.
    competitor: optional counter-offer / price-shock creative inserted into the same feed.
    emotions: "off" | "observe" | "on" (emotion.mode); anything but off asks for a "feel" on the ad and the page."""
    emo_mode = emotion.mode(emotions)
    want_feel = emo_mode != "off"
    meter = client if isinstance(client, UsageMeter) else UsageMeter(client)
    client = meter
    start_usage = meter.snapshot()
    start_by_provider = meter.provider_snapshot()
    rng = random.Random(seed)
    comp = normalize_competitor(competitor) if competitor else None
    creatives, plan = _plan(creatives, people, seed)
    by_id = {p["agent_id"]: p for p in people}
    pools = organic_pools(client, model, [(platform, by_id[aid].get("country", "")) for (aid, platform) in plan],
                          context, parallel, pools, voices=voices)
    traits = {p["agent_id"]: person_habits(p) for p in people}       # the person's own habits, the same in every seed
    emo_w = emotion.weights()
    fx = {p["agent_id"]: emotion.effects(p.get("affect_now"), emo_mode, emo_w) for p in people}   # all 1.0 unless "on"
    exposures = max(1, min(exposures, 6))
    jobs = []
    for (aid, platform), creative in sorted(plan.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        person = by_id[aid]
        pool = pools[(platform, person.get("country", ""))]
        for k in range(1, exposures + 1):
            organic = rng.sample(pool, min(organic_per_feed, len(pool)))
            pos = rng.randint(1, max(1, len(organic) - 1))
            items = [(f"i{j + 1}", o, False) for j, o in enumerate(organic)]
            items.insert(pos, ("ad", creative, True))
            if comp:
                comp_post = {
                    **comp,
                    "platform": platform,
                    "text": comp["text"] + (f" (Price: {comp['price']})" if comp.get("price") and comp["price"] not in comp["text"] else ""),
                }
                comp_pos = min(len(items), pos + 2)
                items.insert(comp_pos, ("comp", comp_post, True))
            items = [(f"i{j + 1}", post, ad) for j, (_, post, ad) in enumerate(items)]
            notice = min(1.0, NOTICE_RATE.get(platform, 0.3) * (1 - 0.6 * traits[aid]["ad_avoidance"])
                         * WEAR_OUT ** ((k - 1) * fx[aid]["wear_out"]) * fx[aid]["notice"])
            jobs.append({"person": person, "platform": platform, "creative": creative, "items": items, "k": k,
                         "hour": rng.choice([7, 9, 12, 13, 18, 20, 21, 22, 23]),
                         "noticed": (rng.random() < notice) if attention_gate else True,
                         "opens_comments": rng.random() < COMMENT_OPEN_RATE, "order": rng.random()})
    jobs.sort(key=lambda j: (j["k"], j["order"]))          # first exposures early, repeats later
    total = len(jobs)
    done = 0
    proof: Dict[str, Dict[str, Any]] = {c["id"]: {"reactions": 0, "shares": 0, "comments": []} for c in creatives}

    def one(job):
        person, platform, creative = job["person"], job["platform"], job["creative"]
        pr = proof[creative["id"]]
        snap = {"reactions": pr["reactions"], "shares": pr["shares"],
                "comments": list(pr["comments"]) if job["opens_comments"] else [],
                "comment_count": len(pr["comments"]), "seen_before": job["k"] - 1}
        feed = [render_item(iid, post, platform, ad, (snap if post.get("id") == creative["id"] else None) if ad else None)
                for iid, post, ad in job["items"]]
        try:
            res_tuple = _llm_json(
                client, model, SYSTEM_PROMPT,
                scroll_prompt(person, platform, feed, job["hour"], traits[person["agent_id"]], feel=want_feel),
                agent_id=person["agent_id"], return_meta=True,
                images=creative_vision.image_parts(creative) if vision == "direct" else None,
            )
            if isinstance(res_tuple, tuple) and len(res_tuple) == 3:
                data, prov, mod = res_tuple
            else:
                data, prov, mod = res_tuple, assigned_provider(client, person["agent_id"], model), model
            rows = data.get("items") if isinstance(data, dict) else data
            acts = {str(r.get("id")): normalize_action(r, platform) for r in rows or [] if isinstance(r, dict)}
        except Exception as e:  # noqa: BLE001 - a failed persona is recorded, not fatal
            logger.warning(f"feed test: {person['name']} on {platform} failed: {e}")
            return job, None, "", ""
        return job, acts, prov, mod

    sessions = []
    waves = max(1, min(waves, 10))
    size = -(-len(jobs) // waves)
    llm_calls = 0
    for w in range(waves):
        batch = jobs[w * size:(w + 1) * size]
        live = [j for j in batch if j["noticed"]]
        llm_calls += len(live)
        results = {}
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            for job, acts, prov, mod in pool.map(one, live):
                results[id(job)] = (acts, prov, mod)
        for job in batch:
            done += 1
            if progress:
                progress(done, total)
            person, platform, creative, items = job["person"], job["platform"], job["creative"], job["items"]
            comp_act = None
            if job["noticed"]:
                entry = results.get(id(job))
                if not entry or entry[0] is None:
                    continue
                acts, prov, mod = entry
                ad_id = next(iid for iid, post, ad in items if ad and post.get("id") == creative["id"])
                ad_act = acts.get(ad_id) or normalize_action({}, platform)
                comp_ids = [iid for iid, post, ad in items if ad and post.get("id") != creative["id"]]
                if comp_ids:
                    comp_act = acts.get(comp_ids[0]) or normalize_action({}, platform)
                organic = [acts.get(iid) or normalize_action({}, platform) for iid, _, ad in items if not ad]
            else:   # never caught their eye: scrolled past without a decision
                ad_act = normalize_action({"stopped": False, "dwell_seconds": round(rng.uniform(0.2, 0.8), 1),
                                           "p_click": 0, "p_react": 0, "p_comment": 0, "p_share": 0, "p_hide": 0},
                                          platform)
                if comp:
                    comp_act = normalize_action({"stopped": False, "dwell_seconds": 0.4, "p_click": 0}, platform)
                organic = []
                # no model call: label the session with the provider this person is routed to
                prov = assigned_provider(client, person["agent_id"], model)
                mod = model
            ad_act["noticed"] = job["noticed"]
            sess_row = {
                "agent_id": person["agent_id"], "name": person["name"], "segment": person["segment"],
                "country": person["country"], "platform": platform, "creative_id": creative["id"], "hour": job["hour"],
                "wave": w + 1, "exposure": job["k"], "saw_proof": bool(proof[creative["id"]]["reactions"]),
                "opened_comments": job["opens_comments"], "ad": ad_act, "organic": organic,
                "traits": traits[person["agent_id"]],
                # the provider that answered this session's call (after any pool failover), not the one that wrote
                # the persona; the persona's generator is kept separately
                "model_provider": prov or assigned_provider(client, person["agent_id"], model),
                "model_name": mod or model,
                "provider_answered": bool(job["noticed"]),
            }
            if person.get("model_provider"):
                sess_row["persona_provider"] = person.get("model_provider")
            if comp_act is not None:
                sess_row["competitor_ad"] = comp_act
            moved = emotion.applied(fx[person["agent_id"]], "notice", "wear_out" if job["k"] > 1 else "notice")
            if moved:
                sess_row["emotion_effects"] = moved
            sessions.append(sess_row)
            pr = proof[creative["id"]]
            pr["reactions"] += 1 if ad_act["reaction"] not in ("none", "downvote") else 0
            pr["shares"] += 1 if ad_act["share"] != "none" else 0
            if ad_act["comment"]:
                pr["comments"].append({"first": str(person["name"]).split()[0], "text": ad_act["comment"][:160]})
    if landing:
        run_landing(client, model, sessions, by_id, {c["id"]: c for c in creatives}, landing, rng, parallel, feel=want_feel,
                    fx=fx)
    failed = sum(1 for j in jobs if j["noticed"]) - sum(1 for s in sessions if s["ad"].get("noticed"))
    if llm_calls and failed == llm_calls:
        raise RuntimeError("No usable model decisions: all noticed exposures failed. Check provider authentication and availability before retrying.")
    summ = summarize(creatives, sessions, benchmarks, competitor=comp)
    if include_generic_baseline:
        try:
            summ["generic_baseline"] = generic_reader_baseline(client, model, creatives, context, summ.get("ranked"))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"generic_reader_baseline failed: {e}")
    end_usage = meter.snapshot()
    usage = {k: end_usage[k] - start_usage[k] for k in end_usage}
    return {"creatives": [creative_vision.strip_sources(c) for c in creatives], "sessions": sessions, "landing": landing,
            "competitor": comp, "waves": waves, "exposures": exposures, "seed": seed, "usage": usage,
            "vision": vision if any(creative_vision.has_visual(c) for c in creatives) else "none",
            "usage_by_provider": provider_diff(meter.provider_snapshot(), start_by_provider),
            "usage_basis": next(iter(meter.usage_sources)) if len(meter.usage_sources) == 1 else "mixed_or_unavailable",
            "realism": {"attention_gate": attention_gate, "notice_rate": NOTICE_RATE, "comment_open_rate": COMMENT_OPEN_RATE,
                        "wear_out": WEAR_OUT, "llm_feed_calls": llm_calls, "emotions": emo_mode},
            "emotion": emotion.run_info(emo_mode, emo_w, sessions),
            "summary": summ,
            "personas_tested": len({s["agent_id"] for s in sessions}), "feeds": total,
            "completion_status": "partial" if failed else "complete", "failed": failed}


def run_landing(client, model: str, sessions: List[Dict[str, Any]], by_id: Dict[int, Dict[str, Any]],
                creatives: Dict[str, Dict[str, Any]], landing: Dict[str, Any], rng: random.Random, parallel: int,
                feel: bool = False, fx: Optional[Dict[Any, Dict[str, float]]] = None) -> None:
    """Clickers: page load on their network vs their patience, then an in-character finish-or-leave decision
    combined with the research-backed Say-vs-Do friction gate (wallet limit, dealbreakers, acquiescence)."""
    todo = []
    for s in sessions:
        if not s["ad"]["click"]:
            continue
        person = by_id[s["agent_id"]]
        net = network_for(person, rng)
        load = round(landing["load_seconds"] * NETWORKS[net], 1)
        pfx = (fx or {}).get(s["agent_id"]) or {}
        patience = round(patience_for(person, rng) * pfx.get("patience", 1.0), 1)
        loaded = load <= patience
        moved = emotion.applied(pfx, "patience")
        if moved:
            s.setdefault("emotion_effects", {}).update(moved)
        s["landing"] = {"network": net, "load_seconds": load, "patience": patience, "loaded": loaded,
                        "read": False, "started_form": False, "completed": False,
                        "friction_gate": "" if loaded else "network_timeout",
                        "drop_reason": "" if loaded else f"left before the page loaded ({load}s on {net})"}
        if loaded:
            todo.append(s)

    def one(s):
        person = by_id[s["agent_id"]]
        try:
            d = _llm_json(client, model, LANDING_SYSTEM,
                          landing_prompt(person, creatives[s["creative_id"]], landing, s["landing"]["load_seconds"], feel=feel),
                          temperature=0.7, max_tokens=600, agent_id=person["agent_id"])
            d = d if isinstance(d, dict) else {}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"landing step failed for {person['name']}: {e}")
            d = {}
        return s, d

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        for s, d in pool.map(one, todo):
            person = by_id[s["agent_id"]]
            completed = bool(d.get("completed"))
            started = bool(d.get("started_form")) or completed
            gate = "completed" if completed else "form_abandon"
            if completed and str(person.get("tech_comfort") or "").lower() == "low" and rng.random() < 0.3:
                completed = False
                gate = "form_abandon"
                d["drop_reason"] = "gave up when the form showed an error or asked for a code"
            if completed:
                pfx = (fx or {}).get(s["agent_id"]) or {}
                friction = check_say_do_friction(person, landing, rng, pfx)
                moved = emotion.applied(pfx, "wallet", "backout")
                if moved:
                    s.setdefault("emotion_effects", {}).update(moved)
                if friction:
                    completed = False
                    gate, reason = friction
                    d["drop_reason"] = reason
            s["landing"].update({"read": bool(d.get("read")) or started, "started_form": started, "completed": completed,
                                 "friction_gate": gate,
                                 "drop_reason": "" if completed else str(d.get("drop_reason") or "")[:200],
                                 "thought": str(d.get("thought") or "")[:160]})
            lf = emotion.normalize_feel(d.get("feel")) if feel else None
            if lf:
                s["landing"]["feel"] = lf


def _proof_effect(ss: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Engagement of first-wave viewers (no social proof) vs later waves (saw reactions and comments)."""
    first = [s["ad"] for s in ss if s.get("wave", 1) == 1]
    later = [s["ad"] for s in ss if s.get("wave", 1) > 1]
    if not first or not later:
        return None
    a, b = _metrics(first), _metrics(later)
    return {"first_wave_engagement": a["engagement_rate"], "later_engagement": b["engagement_rate"],
            "first_wave_ctr": a["ctr"], "later_ctr": b["ctr"], "n_first": len(first), "n_later": len(later)}


def _rate(n: int, d: int) -> Optional[float]:
    return round(100.0 * n / d, 1) if d else None


def _metrics(acts: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(acts)
    stopped = [a for a in acts if a["stopped"]]
    reactions = Counter(a["reaction"] for a in acts if a["reaction"] != "none")
    engaged = sum(1 for a in acts if a["reaction"] != "none" or a["comment"] or a["share"] != "none" or a["save"])
    return {
        "impressions": n,
        "thumb_stop": _rate(len(stopped), n),
        "avg_dwell": round(sum(a["dwell"] for a in stopped) / len(stopped), 1) if stopped else None,
        "watch_pct": round(sum(a["watched_pct"] for a in stopped) / len(stopped)) if stopped else None,
        "ctr": _rate(sum(1 for a in acts if a["click"]), n),
        "engagement_rate": _rate(engaged, n),
        "comment_rate": _rate(sum(1 for a in acts if a["comment"]), n),
        "share_rate": _rate(sum(1 for a in acts if a["share"] != "none"), n),
        "save_rate": _rate(sum(1 for a in acts if a["save"]), n),
        "hide_rate": _rate(sum(1 for a in acts if a["hide"]), n),
        "reactions": dict(reactions.most_common()),
        "clicks": sum(1 for a in acts if a["click"]),
        "comments": sum(1 for a in acts if a["comment"]),
        "shares": sum(1 for a in acts if a["share"] != "none"),
        "saves": sum(1 for a in acts if a["save"]),
        "hides": sum(1 for a in acts if a["hide"]),
        "noticed": _rate(sum(1 for a in acts if a.get("noticed", True)), n),
        "expected_ctr": round(100 * sum(a.get("p_click", 0) for a in acts) / n, 2) if n else None,
        "expected_engagement": round(100 * sum(min(1.0, a.get("p_react", 0) + a.get("p_comment", 0) + a.get("p_share", 0))
                                               for a in acts) / n, 2) if n else None,
    }


def landing_funnel(ss: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    clicked = [s for s in ss if s["ad"]["click"]]
    if not clicked or not any("landing" in s for s in clicked):
        return None
    landed = [s for s in clicked if s.get("landing", {}).get("loaded")]
    started = [s for s in landed if s["landing"].get("started_form")]
    done = [s for s in started if s["landing"].get("completed")]
    reasons = Counter(s["landing"]["drop_reason"] for s in clicked if s.get("landing") and s["landing"].get("drop_reason"))
    gates = Counter(s["landing"].get("friction_gate") for s in clicked if s.get("landing") and s["landing"].get("friction_gate") and not s["landing"].get("completed"))
    nets = Counter(s["landing"]["network"] for s in clicked if s.get("landing"))
    return {"clicks": len(clicked), "page_loaded": len(landed), "form_started": len(started), "converted": len(done),
            "load_rate": _rate(len(landed), len(clicked)), "conversion_after_click": _rate(len(done), len(clicked)),
            "conversion_rate": _rate(len(done), len(ss)),
            "drop_reasons": [{"reason": r, "count": n} for r, n in reasons.most_common(8)],
            "friction_gates": dict(gates),
            "networks": dict(nets)}


def projection(m: Dict[str, Any], lf: Optional[Dict[str, Any]], bench: Optional[Dict[str, Any]],
               calibration: Optional[float]) -> Optional[Dict[str, Any]]:
    """Spend projection from real CPM/budget; CTR optionally calibrated to the real platform CTR."""
    if not bench or not bench.get("cpm") or not bench.get("budget"):
        return None
    try:
        cpm, budget = float(bench["cpm"]), float(bench["budget"])
    except (TypeError, ValueError):
        return None
    ctr = (m.get("expected_ctr") if m.get("expected_ctr") is not None else (m["ctr"] or 0)) / 100 * (calibration or 1.0)
    impressions = budget / cpm * 1000
    clicks = impressions * ctr
    min_clicks = 5
    enough = bool(lf) and (lf.get("clicks") or 0) >= min_clicks
    after_click = (lf["conversion_after_click"] / 100) if enough and lf.get("conversion_after_click") is not None else None
    conversions = clicks * after_click if after_click is not None else None
    out = {"budget": budget, "currency": bench.get("currency") or "", "cpm": cpm, "impressions": round(impressions),
           "ctr_used": round(100 * ctr, 2), "calibrated": bool(calibration), "clicks": round(clicks),
           "cpc": round(budget / clicks, 2) if clicks else None,
           "conversions": round(conversions, 1) if conversions is not None else None,
           "cost_per_conversion": round(budget / conversions, 2) if conversions else None,
           "too_few_clicks": (lf.get("clicks") or 0) if lf and not enough else None}
    out.update(economics(budget, conversions, bench))
    return out


def economics(spend: float, leads: Optional[float], bench: Dict[str, Any]) -> Dict[str, Any]:
    """Lead/sales economics: CPL, customers, CAC, revenue, ROAS, ROI, break-even CPA, payback.

    bench may carry lead_value (value of one conversion), or close_rate (0-1 or %) with deal_value / ltv,
    and gross_margin (0-1 or %) to judge profit rather than revenue."""
    def frac(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v / 100 if v > 1 else v
    if leads is None:
        return {}
    out: Dict[str, Any] = {"cpl": round(spend / leads, 2) if leads else None}
    close = frac(bench.get("close_rate"))
    deal = bench.get("deal_value") or bench.get("ltv") or bench.get("price")
    margin = frac(bench.get("gross_margin")) or 1.0
    lead_value = bench.get("lead_value")
    try:
        deal = float(deal) if deal is not None else None
        lead_value = float(lead_value) if lead_value is not None else None
    except (TypeError, ValueError):
        deal, lead_value = None, None
    if close is not None and deal:
        customers = leads * close
        revenue = customers * deal
        out.update({"customers": round(customers, 1), "cac": round(spend / customers, 2) if customers else None,
                    "revenue": round(revenue, 2)})
        lead_value = lead_value or close * deal
    elif lead_value:
        revenue = leads * lead_value
        out["revenue"] = round(revenue, 2)
    else:
        return out
    profit = revenue * margin - spend
    out.update({"roas": round(revenue / spend, 2) if spend else None,
                "roi_pct": round(100 * profit / spend, 1) if spend else None,
                "profit": round(profit, 2),
                "break_even_cpl": round(lead_value * margin, 2) if lead_value else None})
    monthly = bench.get("monthly_value")
    if monthly and out.get("cac"):
        try:
            out["payback_months"] = round(out["cac"] / (float(monthly) * margin), 1)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return out


GENERIC_READER_SYSTEM = (
    "You are a calibrated direct-response marketing evaluator representing a typical target-market reader "
    "(zero-persona baseline comparator). Score each ad creative objectively on realistic social feed base rates. "
    "Return only valid JSON."
)


def generic_reader_baseline(
    client,
    model: str,
    creatives: List[Dict[str, Any]],
    context: str = "",
    persona_ranked: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Matched-budget zero-persona generic-reader baseline comparator (Maiorano 2026, docs/HUMAN_BEHAVIOR_RESEARCH.md #8).
    Evaluates all creatives in 1 LLM call without individual personas and reports whether the persona panel
    agrees with or diverges from the generic ranker.
    """
    ads_block = "\n".join(
        f"- ID '{c['id']}' ({c['platform']}): Headline: {c.get('headline') or '(none)'} | Text: {c.get('text') or ''} | CTA: {c.get('cta') or ''}"
        for c in creatives
    )
    prompt = (
        f"Context:\n{context[:1200] or 'General consumer campaign'}\n\n"
        f"Creatives to evaluate:\n{ads_block}\n\n"
        "For each creative, estimate realistic feed performance from a generic target-market reader perspective:\n"
        'Return JSON: {"scores": [{"id": "<creative id>", "expected_ctr": 1.2, "thumb_stop": 22.0, '
        '"appeal_0_10": 6.5, "top_concern": "short reason", "verdict": "winner|contender|weak"}]}'
    )
    data = _llm_json(client, model, GENERIC_READER_SYSTEM, prompt, temperature=0.3, max_tokens=2000)
    raw_scores = (data.get("scores") if isinstance(data, dict) else data) or []
    by_cid: Dict[str, Dict[str, Any]] = {}
    for row in raw_scores:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        cid = str(row["id"])
        by_cid[cid] = {
            "id": cid,
            "expected_ctr": round(_num(row.get("expected_ctr"), 0, 100), 2),
            "thumb_stop": round(_num(row.get("thumb_stop"), 0, 100), 1),
            "appeal_0_10": round(_num(row.get("appeal_0_10"), 0, 10), 1),
            "top_concern": str(row.get("top_concern") or "")[:160],
            "verdict": str(row.get("verdict") or "contender")[:40],
        }
    generic_ranked = sorted(
        [c["id"] for c in creatives if c["id"] in by_cid],
        key=lambda cid: (-by_cid[cid]["expected_ctr"], -by_cid[cid]["thumb_stop"], -by_cid[cid]["appeal_0_10"]),
    )
    if not generic_ranked:
        generic_ranked = [c["id"] for c in creatives]
    p_ranked = list(persona_ranked or [])
    top_match = bool(p_ranked and generic_ranked and p_ranked[0] == generic_ranked[0])
    return {
        "scores": by_cid,
        "ranked": generic_ranked,
        "persona_ranked": p_ranked,
        "winner_agrees_with_personas": top_match,
        "note": (
            "Persona panel and generic baseline pick the same top creative."
            if top_match
            else "Persona panel reverses the generic baseline winner due to segment/BDE friction."
        ),
    }


def _provider_key(session: Dict[str, Any]) -> str:
    """The provider family of a session: a session the attention gate scrolled past is labelled with the pool's name
    for the provider (claude_code) and an answered one with the name the response reports (claude); both are one
    group, or the same people would be split into one that only noticed ads and one that never did."""
    from ..utils.model_pool import provider_family
    return provider_family(session.get("model_provider") or "claude") or "claude"


def feelings_summary(ads: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """How the people who noticed an ad felt about it (simulated appraisals, mapped by emotion.appraise)."""
    labelled = []
    for a in ads:
        f = a.get("feel")
        if f:
            r = emotion.appraise(f)
            labelled.append({**f, "emotion": r["emotion"], "intensity": r["intensity"], "_ad": a})
    if not labelled:
        return None
    n = len(labelled)
    counts = Counter(f["emotion"] for f in labelled)
    pleasant = [float(f["pleasant"]) for f in labelled if f.get("pleasant") is not None]
    clicked = [f for f in labelled if f["_ad"].get("click")]
    return {"n": n, "neutral_share": round(counts.get("neutral", 0) / n, 3),
            "emotions": {k: round(v / n, 3) for k, v in counts.most_common()},
            "mean_pleasant": round(sum(pleasant) / len(pleasant), 3) if pleasant else None,
            "clicked_after": {k: round(v / len(clicked), 3) for k, v in Counter(f["emotion"] for f in clicked).most_common()} if clicked else {},
            "words": [f["words"] for f in labelled if f.get("words") and f["emotion"] != "neutral"][:12],
            "flags": emotion.quality_flags(labelled), "basis": "simulated"}


def summarize(creatives: List[Dict[str, Any]], sessions: List[Dict[str, Any]],
              benchmarks: Optional[Dict[str, Any]] = None,
              competitor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    benchmarks = benchmarks or {}
    per: Dict[str, Any] = {}
    calib: Dict[str, Optional[float]] = {}
    for platform in {c["platform"] for c in creatives}:
        b = benchmarks.get(platform) or benchmarks.get("default") or {}
        ads = [s["ad"] for s in sessions if s["platform"] == platform]
        mm = _metrics(ads) if ads else {}
        sim_ctr = (mm.get("expected_ctr") if mm.get("expected_ctr") is not None else mm.get("ctr")) or 0
        real = b.get("ctr")
        calib[platform] = (float(real) / sim_ctr) if real and sim_ctr else None
    for c in creatives:
        ss = [s for s in sessions if s["creative_id"] == c["id"]]
        if not ss:
            continue
        seg = defaultdict(list)
        prov_groups = defaultdict(list)
        for s in ss:
            seg[s["segment"]].append(s["ad"])
            prov_groups[_provider_key(s)].append(s["ad"])
        m = _metrics([s["ad"] for s in ss])
        lf = landing_funnel(ss)
        bench = benchmarks.get(c["platform"]) or benchmarks.get("default")
        per[c["id"]] = {
            **m, "landing": lf, "projection": projection(m, lf, bench, calib.get(c["platform"])),
            "by_exposure": [{"exposure": k, **{kk: vv for kk, vv in _metrics([s["ad"] for s in ss if s.get("exposure", 1) == k]).items()
                                               if kk in ("impressions", "noticed", "thumb_stop", "ctr", "expected_ctr")}}
                            for k in sorted({s.get("exposure", 1) for s in ss})],
            "proof_effect": _proof_effect(ss),
            "by_segment": sorted([{"key": k, **_metrics(v)} for k, v in seg.items()],
                                 key=lambda r: (-(r["ctr"] or 0), -(r["engagement_rate"] or 0))),
            "by_provider": sorted([{"provider": k, **_metrics(v)} for k, v in prov_groups.items()],
                                  key=lambda r: r["provider"]),
            "comments_list": [{"name": s["name"], "segment": s["segment"], "text": s["ad"]["comment"],
                               "reaction": s["ad"]["reaction"]} for s in ss if s["ad"]["comment"]],
            "feelings": feelings_summary([s["ad"] for s in ss]),
            "thoughts": [{"name": s["name"], "segment": s["segment"], "text": s["ad"]["thought"],
                          "stopped": s["ad"]["stopped"], "click": s["ad"]["click"]} for s in ss if s["ad"]["thought"]][:40],
            "events": [{"name": s["name"], "segment": s["segment"], "wave": s.get("wave", 1),
                        "exposure": s.get("exposure", 1), "noticed": s["ad"].get("noticed", True),
                        "model_provider": s.get("model_provider"),
                        **{k: s["ad"][k] for k in
                           ("stopped", "dwell", "reaction", "comment", "share", "save", "click", "hide", "thought")},
                        **({"landing": s["landing"]} if s.get("landing") else {})}
                       for s in sorted(ss, key=lambda x: x.get("wave", 1))],
        }
    baseline = {}
    for platform in {s["platform"] for s in sessions}:
        organic = [a for s in sessions if s["platform"] == platform for a in s["organic"]]
        baseline[platform] = _metrics(organic)
    ranked = sorted(per, key=lambda cid: (-((per[cid]["landing"] or {}).get("conversion_rate") or 0),
                                          -(per[cid].get("expected_ctr") or per[cid]["ctr"] or 0),
                                          -(per[cid]["thumb_stop"] or 0)))

    # Overall cross-provider breakdown across all sessions
    all_by_prov: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in sessions:
        all_by_prov[_provider_key(s)].append(s)
    by_provider_summary: Dict[str, Any] = {}
    prov_winners: Dict[str, str] = {}
    for prov, p_sessions in sorted(all_by_prov.items()):
        pm = _metrics([s["ad"] for s in p_sessions])
        plf = landing_funnel(p_sessions)
        # Find which creative won under this provider
        c_scores = {}
        for cid in per:
            c_acts = [s["ad"] for s in p_sessions if s["creative_id"] == cid]
            if c_acts:
                cm = _metrics(c_acts)
                c_scores[cid] = (cm.get("expected_ctr") or cm.get("ctr") or 0, cm.get("thumb_stop") or 0)
        winner = max(c_scores, key=lambda k: c_scores[k]) if c_scores else None
        if winner:
            prov_winners[prov] = winner
        by_provider_summary[prov] = {
            "provider": prov,
            "sessions": len(p_sessions),
            "personas": len({s["agent_id"] for s in p_sessions}),
            "thumb_stop": pm["thumb_stop"],
            "ctr": pm["ctr"],
            "expected_ctr": pm["expected_ctr"],
            "engagement_rate": pm["engagement_rate"],
            "hide_rate": pm["hide_rate"],
            "conversion_rate": plf["conversion_rate"] if plf else None,
            "winner": winner,
        }

    # Competitor counter-offer / price-shock summary when tested
    comp_summary = None
    comp_sessions = [s for s in sessions if s.get("competitor_ad")]
    if comp_sessions:
        comp_acts = [s["competitor_ad"] for s in comp_sessions]
        brand_acts = [s["ad"] for s in comp_sessions]
        cm = _metrics(comp_acts)
        bm = _metrics(brand_acts)
        b_clicks = bm["clicks"]
        c_clicks = cm["clicks"]
        defected = sum(1 for s in comp_sessions if s["competitor_ad"]["click"] and not s["ad"]["click"])
        both_clicked = sum(1 for s in comp_sessions if s["competitor_ad"]["click"] and s["ad"]["click"])
        denom = max(1, b_clicks + c_clicks)
        comp_summary = {
            "name": (competitor or {}).get("name") or "Competitor",
            "price": (competitor or {}).get("price") or "",
            "headline": (competitor or {}).get("headline") or (competitor or {}).get("text") or "",
            "impressions": len(comp_sessions),
            "brand_thumb_stop": bm["thumb_stop"],
            "competitor_thumb_stop": cm["thumb_stop"],
            "brand_ctr": bm["ctr"],
            "competitor_ctr": cm["ctr"],
            "brand_expected_ctr": bm["expected_ctr"],
            "competitor_expected_ctr": cm["expected_ctr"],
            "brand_win_share_pct": round(100.0 * b_clicks / denom, 1) if (b_clicks or c_clicks) else 50.0,
            "defection_rate": _rate(defected, len(comp_sessions)),
            "both_clicked": both_clicked,
        }

    out = {
        "per_creative": per,
        "calibration": calib,
        "organic_baseline": {k: {kk: vv for kk, vv in v.items() if kk not in ("reactions",)} for k, v in baseline.items()},
        "ranked": ranked,
        "by_provider": by_provider_summary,
    }
    if comp_summary:
        out["competitor_shock"] = comp_summary
    return out


# --------------------------------------------------------------------------
# Multi-seed runs: the same test with different seeds, reported as a range
# --------------------------------------------------------------------------

SEED_METRICS = ("expected_ctr", "ctr", "thumb_stop", "engagement_rate", "expected_engagement", "hide_rate")


def seed_list(seed: int = 5, n: int = 1) -> List[int]:
    return [int(seed) + 7919 * i for i in range(max(1, int(n)))]


def _spread(values: List[Optional[float]]) -> Optional[Dict[str, Any]]:
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return None
    mean = sum(xs) / len(xs)
    sd = (sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5 if len(xs) > 1 else 0.0
    return {"mean": round(mean, 2), "min": round(min(xs), 2), "max": round(max(xs), 2), "sd": round(sd, 2),
            "values": [None if v is None else round(float(v), 2) for v in values]}


def combine_runs(runs: List[Dict[str, Any]], benchmarks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pool the sessions of several seeds and keep, per creative, the mean and min-max range across seeds."""
    first = runs[0]
    sessions = [{**s, "seed": r.get("seed")} for r in runs for s in r["sessions"]]
    summary = summarize(first["creatives"], sessions, benchmarks, competitor=first.get("competitor"))
    first_per = first["summary"]["per_creative"]
    for cid, m in summary["per_creative"].items():
        if cid in first_per:            # replay one seed, so the same person does not scroll past twice
            m["events"] = first_per[cid]["events"]
    per_seed = [{"seed": r.get("seed"), "usage": r.get("usage") or {}, "ranked": r["summary"]["ranked"],
                 "failed": r.get("failed", 0),
                 "per_creative": {cid: {k: m.get(k) for k in SEED_METRICS + ("impressions",)}
                                  for cid, m in r["summary"]["per_creative"].items()}} for r in runs]
    spread = {cid: {k: _spread([ps["per_creative"].get(cid, {}).get(k) for ps in per_seed]) for k in SEED_METRICS}
              for cid in summary["per_creative"]}
    winners = Counter(ps["ranked"][0] for ps in per_seed if ps["ranked"])
    usage = {k: sum(int((r.get("usage") or {}).get(k, 0)) for r in runs) for k in ("calls", "input_tokens", "output_tokens")}
    top = (summary.get("ranked") or [None])[0]
    multi = {"n": len(runs), "seeds": [r.get("seed") for r in runs], "per_seed": per_seed, "spread": spread,
             "winner_counts": dict(winners.most_common()),
             "winner_agreement": round(100.0 * winners.get(top, 0) / len(runs)) if top else None, "usage": usage}
    return {**first, "sessions": sessions, "summary": summary, "seed": first.get("seed"), "usage": usage,
            "usage_by_provider": add_provider_usage(*[r.get("usage_by_provider") for r in runs]),
            "multi_seed": multi, "feeds": sum(r.get("feeds", 0) for r in runs),
            "failed": sum(r.get("failed", 0) for r in runs),
            "realism": {**first.get("realism", {}),
                        "llm_feed_calls": sum((r.get("realism") or {}).get("llm_feed_calls", 0) for r in runs)}}


def run_multi_seed(client, model: str, creatives: List[Dict[str, Any]], people: List[Dict[str, Any]],
                   seeds: Optional[List[int]] = None, progress: Optional[Callable[[int, int], None]] = None,
                   benchmarks: Optional[Dict[str, Any]] = None, **kw) -> Dict[str, Any]:
    """Run the feed test once per seed (assignment, placements, attention and traits all change) and combine.

    One seed returns the plain single-run result. The organic pools are generated once and shared by every
    seed, and the seeds run concurrently (FEED_TEST_SEED_WORKERS, default 4). Every run logs its model calls
    and tokens; the shared pool calls are counted in the first seed's usage."""
    seeds = list(seeds or [5])
    # seeds run concurrently, so each gets its own meter on the raw client: per-seed counts stay exact
    base = client._client if isinstance(client, UsageMeter) else client
    pools: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    shared = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    shared_by_provider: Dict[str, Dict[str, int]] = {}
    # the generic-reader baseline compares against the pooled ranking, so with several seeds it runs once on the
    # combined result instead of once per seed (combine_runs re-summarises and would drop the per-seed ones)
    want_baseline = bool(kw.pop("include_generic_baseline", False))
    if len(seeds) == 1:
        kw["include_generic_baseline"] = want_baseline
    if len(seeds) > 1:
        by_id = {p["agent_id"]: p for p in people}
        keys = set()
        for sd in seeds:
            _, plan = _plan(creatives, people, sd)
            keys |= {(platform, by_id[aid].get("country", "")) for (aid, platform) in plan}
        pool_meter = UsageMeter(base)
        organic_pools(pool_meter, model, sorted(keys), kw.get("context", ""), int(kw.get("parallel") or 8), pools, kw.get("voices"))
        shared = pool_meter.snapshot()
        shared_by_provider = pool_meter.provider_snapshot()
    lock = threading.Lock()
    done_by_seed: Dict[int, int] = {}
    total_by_seed: Dict[int, int] = {}

    def run_one(i: int, sd: int) -> Dict[str, Any]:
        def prog(done, total, i=i):
            if not progress:
                return
            with lock:
                done_by_seed[i], total_by_seed[i] = done, total
                known = sum(total_by_seed.values())
                est_total = known + (len(seeds) - len(total_by_seed)) * (known // max(1, len(total_by_seed)))
                progress(sum(done_by_seed.values()), max(est_total, 1))
        r = run_feed_test(UsageMeter(base), model, creatives, people, seed=sd, progress=prog,
                          benchmarks=benchmarks, pools=pools, **kw)
        u = r["usage"]
        logger.info(f"feed test seed {sd} ({i + 1}/{len(seeds)}): {u['calls']} model calls, "
                    f"{u['input_tokens']} input / {u['output_tokens']} output tokens")
        return r

    if len(seeds) == 1:
        return run_one(0, seeds[0])
    with ThreadPoolExecutor(max_workers=max(1, min(SEED_WORKERS, len(seeds)))) as ex:
        runs = list(ex.map(lambda args: run_one(*args), list(enumerate(seeds))))
    for k, v in shared.items():
        runs[0]["usage"][k] = int(runs[0]["usage"].get(k, 0)) + int(v)
    runs[0]["usage_by_provider"] = add_provider_usage(runs[0].get("usage_by_provider"), shared_by_provider)
    combined = combine_runs(runs, benchmarks)
    if want_baseline:
        meter = UsageMeter(base)
        try:
            combined["summary"]["generic_baseline"] = generic_reader_baseline(
                meter, model, combined["creatives"], kw.get("context", ""), combined["summary"].get("ranked"))
        except Exception as e:  # noqa: BLE001 - the comparator is optional
            logger.warning(f"generic_reader_baseline failed: {e}")
        extra = meter.snapshot()
        for k, v in extra.items():
            combined["usage"][k] = int(combined["usage"].get(k, 0)) + int(v)
        combined["usage_by_provider"] = add_provider_usage(combined.get("usage_by_provider"), meter.provider_snapshot())
    return combined

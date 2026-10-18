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
import random
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def landing_prompt(person: Dict[str, Any], creative: Dict[str, Any], landing: Dict[str, Any], waited: float) -> str:
    fields = ", ".join(landing["form_fields"]) or "no form"
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
                       "communities": m.get("communities") or [], "income": m.get("income"),
                       "thinking_style": m.get("thinking_style"), "tech_comfort": m.get("tech_comfort")})
    if any(m.get("kind") == "persona" for m in meta.values()):
        people = [x for x in people if meta.get(x["agent_id"], {}).get("kind") == "persona"]
    return people


def targets(creative: Dict[str, Any], person: Dict[str, Any]) -> bool:
    if creative["segments"] and person["segment"] not in creative["segments"]:
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

def _llm_json(client, model: str, system: str, prompt: str, temperature: float = 0.8, max_tokens: int = 3000) -> Any:
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = create_chat_completion(client, model=model, temperature=max(0.3, temperature - 0.2 * attempt),
                                          max_tokens=max_tokens,
                                          messages=[{"role": "system", "content": system},
                                                    {"role": "user", "content": prompt}])
            return parse_json_block(extract_chat_completion_text(resp))
        except Exception as e:  # noqa: BLE001 - retried then raised
            last = e
            logger.warning(f"feed test LLM call failed (attempt {attempt + 1}): {str(e)[:120]}")
    raise RuntimeError(f"feed test LLM call failed: {last}")


def organic_pool(client, model: str, platform: str, country: str, context: str, n: int = 10) -> List[Dict[str, Any]]:
    label = PLATFORMS[platform]["label"]
    prompt = (f"Write {n} varied {label} feed posts that a typical person in {country or 'this audience'} would see "
              f"today, in the languages people there actually post in. Some background on the audience:\n"
              f"{context[:1500]}\n\nReturn JSON: {{\"posts\": [{{\"kind\": \"friend|family|group|page|creator|news|meme\", "
              f"\"author\": \"invented name or page\", \"text\": \"post text\", \"media\": \"what the photo/video shows, or empty\"}}]}}")
    try:
        data = _llm_json(client, model, ORGANIC_SYSTEM, prompt, temperature=0.9, max_tokens=2500)
        posts = [p for p in (data.get("posts") if isinstance(data, dict) else data) or [] if isinstance(p, dict) and p.get("text")]
        if len(posts) >= 4:
            return posts
    except Exception as e:  # noqa: BLE001 - fall back to generic posts
        logger.warning(f"organic posts for {platform}/{country} failed, using fallback: {e}")
    return list(FALLBACK_ORGANIC)


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
                  habits: Optional[Dict[str, Any]] = None) -> str:
    pb = PLATFORMS[platform]
    reactions = "|".join(["none"] + pb["reactions"])
    h = habits or {}
    facts = ""
    if h:
        facts = (f"Your habits (facts, not suggestions): you ignore most ads (ad avoidance {h['ad_avoidance']} on a 0-1 scale); "
                 f"you comment on posts {h['comments']}; you {h['clicks_ads']} click on ads; you share things {h['shares']}. "
                 "You do not know typical prices or what other products cost unless the post says so.\n")
    return (
        f"Who you are:\n{person['persona']}\n(Age {person.get('age')}, {person.get('gender')}, {person.get('country')}.)\n{facts}\n"
        f"It is {hour}:00 and you are scrolling {pb['label']} on your phone.\nHow people behave here: {pb['playbook']}\n\n"
        "Your feed, top to bottom:\n\n" + "\n\n".join(feed) + "\n\n"
        "For EVERY item say what you actually do. Your options, most common first: scroll past, glance, stop and read, "
        "react, comment, share, click. Most items should be a quick scroll past with no action.\n"
        "For the Sponsored/Promoted item also give your honest probabilities (0-1) of each action if you saw it on a "
        "normal day: p_click, p_react, p_comment, p_share, p_hide.\n"
        "Return JSON: {\"items\": [{\"id\": \"i1\", \"stopped\": false, \"dwell_seconds\": 0.5, \"watched_pct\": 0, "
        f"\"reaction\": \"{reactions}\", \"comment\": \"what you type, or empty\", \"share\": \"none|share|send\", "
        "\"save\": false, \"click\": false, \"hide\": false, \"thought\": \"your honest inner reaction in under 15 words\", "
        "\"p_click\": 0.0, \"p_react\": 0.0, \"p_comment\": 0.0, \"p_share\": 0.0, \"p_hide\": 0.0}]}"
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
    return out


# Realism controls (see README "How realistic is it?"):
# chance an ad catches the eye at all on each platform, before any LLM call
NOTICE_RATE = {"facebook": 0.30, "instagram": 0.35, "reddit": 0.25, "tiktok": 0.40, "linkedin": 0.30, "x": 0.25}
COMMENT_OPEN_RATE = 0.35        # share of viewers who open the comments under an ad
WEAR_OUT = 0.8                   # each repeat exposure multiplies the notice chance by this


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
                  exposures: int = 2, attention_gate: bool = True) -> Dict[str, Any]:
    """waves: later waves see earlier reaction counts (and, if they open them, comments).
    exposures: how many times each person scrolls past the ad (frequency, with wear-out).
    attention_gate: decide in code whether the ad is noticed at all; unnoticed ads are a quick scroll past.
    landing: optional page model; clickers face load time on their network, then decide to finish or leave.
    benchmarks: optional {platform: {cpm, ctr, budget, currency, lead_value, ...}} for projections."""
    rng = random.Random(seed)
    plan = assign(creatives, people, seed)
    if not plan:
        raise ValueError("no persona matches the creatives' targeting")
    pools: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for (aid, platform) in plan:
        country = next((p["country"] for p in people if p["agent_id"] == aid), "")
        if (platform, country) not in pools:
            pools[(platform, country)] = organic_pool(client, model, platform, country, context)
    by_id = {p["agent_id"]: p for p in people}
    traits = {p["agent_id"]: behaviour_traits(p, random.Random(seed * 1000 + int(p["agent_id"]))) for p in people}
    exposures = max(1, min(exposures, 6))
    jobs = []
    for (aid, platform), creative in sorted(plan.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        person = by_id[aid]
        pool = pools[(platform, person["country"])]
        for k in range(1, exposures + 1):
            organic = rng.sample(pool, min(organic_per_feed, len(pool)))
            pos = rng.randint(1, max(1, len(organic) - 1))
            items = [(f"i{j + 1}", o, False) for j, o in enumerate(organic)]
            items.insert(pos, ("ad", creative, True))
            items = [(f"i{j + 1}", post, ad) for j, (_, post, ad) in enumerate(items)]
            notice = NOTICE_RATE.get(platform, 0.3) * (1 - 0.6 * traits[aid]["ad_avoidance"]) * WEAR_OUT ** (k - 1)
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
        feed = [render_item(iid, post, platform, ad, snap if ad else None) for iid, post, ad in job["items"]]
        try:
            data = _llm_json(client, model, SYSTEM_PROMPT,
                             scroll_prompt(person, platform, feed, job["hour"], traits[person["agent_id"]]))
            rows = data.get("items") if isinstance(data, dict) else data
            acts = {str(r.get("id")): normalize_action(r, platform) for r in rows or [] if isinstance(r, dict)}
        except Exception as e:  # noqa: BLE001 - a failed persona is recorded, not fatal
            logger.warning(f"feed test: {person['name']} on {platform} failed: {e}")
            return job, None
        return job, acts

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
            for job, acts in pool.map(one, live):
                results[id(job)] = acts
        for job in batch:
            done += 1
            if progress:
                progress(done, total)
            person, platform, creative, items = job["person"], job["platform"], job["creative"], job["items"]
            if job["noticed"]:
                acts = results.get(id(job))
                if acts is None:
                    continue
                ad_id = next(iid for iid, _, ad in items if ad)
                ad_act = acts.get(ad_id) or normalize_action({}, platform)
                organic = [acts.get(iid) or normalize_action({}, platform) for iid, _, ad in items if not ad]
            else:   # never caught their eye: scrolled past without a decision
                ad_act = normalize_action({"stopped": False, "dwell_seconds": round(rng.uniform(0.2, 0.8), 1),
                                           "p_click": 0, "p_react": 0, "p_comment": 0, "p_share": 0, "p_hide": 0},
                                          platform)
                organic = []
            ad_act["noticed"] = job["noticed"]
            sessions.append({
                "agent_id": person["agent_id"], "name": person["name"], "segment": person["segment"],
                "country": person["country"], "platform": platform, "creative_id": creative["id"], "hour": job["hour"],
                "wave": w + 1, "exposure": job["k"], "saw_proof": bool(proof[creative["id"]]["reactions"]),
                "opened_comments": job["opens_comments"], "ad": ad_act, "organic": organic,
                "traits": traits[person["agent_id"]],
            })
            pr = proof[creative["id"]]
            pr["reactions"] += 1 if ad_act["reaction"] not in ("none", "downvote") else 0
            pr["shares"] += 1 if ad_act["share"] != "none" else 0
            if ad_act["comment"]:
                pr["comments"].append({"first": str(person["name"]).split()[0], "text": ad_act["comment"][:160]})
    if landing:
        run_landing(client, model, sessions, by_id, {c["id"]: c for c in creatives}, landing, rng, parallel)
    return {"creatives": creatives, "sessions": sessions, "landing": landing, "waves": waves, "exposures": exposures,
            "realism": {"attention_gate": attention_gate, "notice_rate": NOTICE_RATE, "comment_open_rate": COMMENT_OPEN_RATE,
                        "wear_out": WEAR_OUT, "llm_feed_calls": llm_calls},
            "summary": summarize(creatives, sessions, benchmarks),
            "personas_tested": len({s["agent_id"] for s in sessions}), "feeds": total,
            "failed": sum(1 for j in jobs if j["noticed"]) - sum(1 for s in sessions if s["ad"].get("noticed"))}


def run_landing(client, model: str, sessions: List[Dict[str, Any]], by_id: Dict[int, Dict[str, Any]],
                creatives: Dict[str, Dict[str, Any]], landing: Dict[str, Any], rng: random.Random, parallel: int) -> None:
    """Clickers: page load on their network vs their patience, then an in-character finish-or-leave decision."""
    todo = []
    for s in sessions:
        if not s["ad"]["click"]:
            continue
        person = by_id[s["agent_id"]]
        net = network_for(person, rng)
        load = round(landing["load_seconds"] * NETWORKS[net], 1)
        patience = patience_for(person, rng)
        s["landing"] = {"network": net, "load_seconds": load, "patience": patience, "loaded": load <= patience,
                        "read": False, "started_form": False, "completed": False,
                        "drop_reason": "" if load <= patience else f"left before the page loaded ({load}s on {net})"}
        if load <= patience:
            todo.append(s)

    def one(s):
        person = by_id[s["agent_id"]]
        try:
            d = _llm_json(client, model, LANDING_SYSTEM,
                          landing_prompt(person, creatives[s["creative_id"]], landing, s["landing"]["load_seconds"]),
                          temperature=0.7, max_tokens=600)
            d = d if isinstance(d, dict) else {}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"landing step failed for {person['name']}: {e}")
            d = {}
        return s, d

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        for s, d in pool.map(one, todo):
            completed = bool(d.get("completed"))
            if completed and str(by_id[s["agent_id"]].get("tech_comfort") or "").lower() == "low" and rng.random() < 0.3:
                completed = False
                d["drop_reason"] = "gave up when the form showed an error or asked for a code"
            started = bool(d.get("started_form")) or completed
            s["landing"].update({"read": bool(d.get("read")) or started, "started_form": started, "completed": completed,
                                 "drop_reason": "" if completed else str(d.get("drop_reason") or "")[:200],
                                 "thought": str(d.get("thought") or "")[:160]})


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
    nets = Counter(s["landing"]["network"] for s in clicked if s.get("landing"))
    return {"clicks": len(clicked), "page_loaded": len(landed), "form_started": len(started), "converted": len(done),
            "load_rate": _rate(len(landed), len(clicked)), "conversion_after_click": _rate(len(done), len(clicked)),
            "conversion_rate": _rate(len(done), len(ss)),
            "drop_reasons": [{"reason": r, "count": n} for r, n in reasons.most_common(8)], "networks": dict(nets)}


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
    after_click = (lf["conversion_after_click"] / 100) if lf and lf.get("conversion_after_click") is not None else None
    conversions = clicks * after_click if after_click is not None else None
    out = {"budget": budget, "currency": bench.get("currency") or "", "cpm": cpm, "impressions": round(impressions),
           "ctr_used": round(100 * ctr, 2), "calibrated": bool(calibration), "clicks": round(clicks),
           "cpc": round(budget / clicks, 2) if clicks else None,
           "conversions": round(conversions, 1) if conversions is not None else None,
           "cost_per_conversion": round(budget / conversions, 2) if conversions else None}
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


def summarize(creatives: List[Dict[str, Any]], sessions: List[Dict[str, Any]],
              benchmarks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        for s in ss:
            seg[s["segment"]].append(s["ad"])
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
            "comments_list": [{"name": s["name"], "segment": s["segment"], "text": s["ad"]["comment"],
                               "reaction": s["ad"]["reaction"]} for s in ss if s["ad"]["comment"]],
            "thoughts": [{"name": s["name"], "segment": s["segment"], "text": s["ad"]["thought"],
                          "stopped": s["ad"]["stopped"], "click": s["ad"]["click"]} for s in ss if s["ad"]["thought"]][:40],
            "events": [{"name": s["name"], "segment": s["segment"], "wave": s.get("wave", 1),
                        "exposure": s.get("exposure", 1), "noticed": s["ad"].get("noticed", True),
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
    return {"per_creative": per, "calibration": calib, "organic_baseline": {k: {kk: vv for kk, vv in v.items() if kk not in ("reactions",)}
                                                      for k, v in baseline.items()}, "ranked": ranked}

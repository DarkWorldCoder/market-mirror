"""
MarketMirror: per-round persona cards for OASIS agents.

OASIS gives every agent the same generic instruction each round ("pick an action, don't just like").
That makes personas drift toward generic English and over-engagement. This module prepends a compact
persona card to every observation prompt: who they are, where they live, how people there write online,
their habits, and that scrolling past (do_nothing) is the normal outcome. It also gives each round a small
action budget and a mood, so activity varies the way it does for real people.

Install once per platform after the agent graph is built:

    from agent_context import install, begin_round
    install(agent_graph, config, seed=7)      # patches SocialEnvironment.to_text_prompt (idempotent)
    ...
    begin_round(round_num, simulated_hour)    # before env.step(...) each round

Cards come from simulation_config.json: persona_index (name, segment, country, city, languages,
platform_habits, communities), agent_configs[].activity_level and community_config.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

_STATE: Dict[str, Any] = {"cards": {}, "budgets": {}, "moods": {}, "round": 0, "hour": 12, "rng": random.Random(7),
                          "activity": {}, "installed": False}

MOODS = ["relaxed", "bored", "in a hurry", "tired after work", "curious", "irritated by something earlier",
         "happy", "stressed about money", "distracted", "chatty"]
COMMENT_RATE = {0.0: "almost never", 0.3: "a few times a year", 0.5: "about once a month",
                0.7: "about once a week", 0.85: "a few times a week"}


def _rate_label(activity: float) -> str:
    label = "almost never"
    for threshold, text in sorted(COMMENT_RATE.items()):
        if activity >= threshold:
            label = text
    return label


def persona_cards(config: Dict[str, Any]) -> Dict[int, str]:
    """agent_id -> card text. Graph actors (brand, companies) get a short organisation card."""
    cfg = config or {}
    index = [r for r in cfg.get("persona_index") or [] if isinstance(r, dict) and r.get("agent_id") is not None]
    activity = {int(a.get("agent_id")): float(a.get("activity_level") or 0.5)
                for a in cfg.get("agent_configs") or [] if isinstance(a, dict) and a.get("agent_id") is not None}
    communities = {}
    for c in (cfg.get("community_config") or {}).get("communities") or []:
        for m in c.get("member_ids") or []:
            communities.setdefault(int(m), []).append(c.get("name"))
    cards: Dict[int, str] = {}
    for r in index:
        aid = int(r["agent_id"])
        kind = r.get("kind") or "persona"
        name = r.get("name") or f"agent {aid}"
        if kind == "community":
            cards[aid] = (f"You run the account of {name}, a {r.get('entity_type') or 'community'} group. You post "
                          f"what members care about, in the members' language, and moderate politely. You do not "
                          f"advertise; you share, ask and warn.")
            continue
        if kind == "graph":
            cards[aid] = (f"You are the official account of {name}. You post rarely, in a professional tone, and "
                          f"reply only to direct questions about {name}. Do nothing most rounds.")
            continue
        langs = ", ".join(r.get("languages") or []) or "the local language mixed with English"
        where = ", ".join(x for x in (r.get("city"), r.get("country")) if x) or "your city"
        groups = communities.get(aid) or r.get("communities") or []
        bits = [f"You are {name}, {r.get('age') or 'adult'}, {r.get('occupation') or r.get('segment') or 'a person'} in {where}.",
                f"Write the way people in {r.get('country') or 'your country'} actually post online: {langs} mixed "
                f"the way you speak, short, local references, emoji or slang if that is you.",
                f"You comment on posts {_rate_label(activity.get(aid, 0.5))} and you ignore most ads unless they "
                f"are relevant to you right now."]
        if r.get("platform_habits"):
            bits.append(f"Your habits: {str(r['platform_habits'])[:160]}.")
        if groups:
            bits.append(f"You are in these groups: {', '.join(map(str, groups[:3]))}; you trust people there more than brands.")
        if r.get("thinking_style"):
            bits.append(f"How you think: {r['thinking_style']}.")
        bits.append("Scrolling past is normal. If nothing deserves a reply, do_nothing is the right answer.")
        cards[aid] = " ".join(bits)
    _STATE["activity"] = activity
    return cards


def round_flavour(agent_id: int, round_num: int, hour: int, rng: random.Random,
                  activity: Optional[Dict[int, float]] = None) -> Tuple[int, str]:
    """(action budget 1-3, mood) for one agent this round. More active people and evening hours get bigger budgets."""
    act = (activity or _STATE["activity"]).get(agent_id, 0.5)
    peak = 1.0 if 18 <= hour <= 23 or 12 <= hour <= 13 else 0.7 if 7 <= hour <= 17 else 0.4
    x = rng.random() * act * peak
    budget = 3 if x > 0.55 else 2 if x > 0.25 else 1
    mood = rng.choice(MOODS)
    if 0 <= hour <= 5:
        mood = rng.choice(["tired", "can't sleep", "bored"])
    return budget, mood


def begin_round(round_num: int, hour: int) -> None:
    """Refresh every agent's budget and mood for the coming round (deterministic for a seed)."""
    rng = _STATE["rng"]
    _STATE["round"], _STATE["hour"] = round_num, hour
    for aid in list(_STATE["cards"]):
        _STATE["budgets"][aid], _STATE["moods"][aid] = round_flavour(aid, round_num, hour, rng)


def session_line(agent_id: int) -> str:
    budget = _STATE["budgets"].get(agent_id, 1)
    mood = _STATE["moods"].get(agent_id, "relaxed")
    hour = _STATE["hour"]
    return (f"Right now it is about {hour:02d}:00 and you feel {mood}. You have time for at most {budget} "
            f"action(s) this session. If nothing deserves a reply, do_nothing.")


def card_for(agent_id: int) -> str:
    return _STATE["cards"].get(agent_id, "")


def install(agent_graph: Any, config: Dict[str, Any], seed: int = 7) -> int:
    """Attach cards to the agents in `agent_graph` and patch SocialEnvironment.to_text_prompt once.
    Returns the number of agents that got a card."""
    _STATE["cards"] = persona_cards(config)
    _STATE["rng"] = random.Random(seed)
    begin_round(0, 12)
    n = 0
    try:
        agents = list(agent_graph.get_agents()) if hasattr(agent_graph, "get_agents") else []
    except Exception:  # noqa: BLE001 - graph shapes differ between OASIS versions
        agents = []
    for item in agents:
        agent = item[1] if isinstance(item, tuple) else item
        aid = getattr(agent, "social_agent_id", None)
        if aid in _STATE["cards"]:
            n += 1
    _patch_environment()
    return n


def _patch_environment() -> None:
    if _STATE["installed"]:
        return
    try:
        from oasis.social_agent.agent_environment import SocialEnvironment
    except ImportError:  # pragma: no cover - only when OASIS is absent (tests)
        return
    original = SocialEnvironment.to_text_prompt

    async def to_text_prompt(self, *args, **kwargs):
        base = await original(self, *args, **kwargs)
        return compose_prompt(getattr(getattr(self, "action", None), "agent_id", None), base)

    SocialEnvironment.to_text_prompt = to_text_prompt
    try:
        tmpl = SocialEnvironment.env_template.template
        SocialEnvironment.env_template.template = tmpl.replace(
            "pick one you want to perform action that best reflects your current inclination based on your "
            "profile and posts content. Do not limit your action in just `like` to like posts",
            "React only the way this specific person would. Most posts deserve nothing from you.")
    except AttributeError:  # pragma: no cover
        pass
    _STATE["installed"] = True


def compose_prompt(agent_id: Optional[int], base: str) -> str:
    """Card + original observation + session line. Pure, so it is unit-testable without OASIS."""
    if agent_id is None or agent_id not in _STATE["cards"]:
        return base
    return f"{_STATE['cards'][agent_id]}\n\n{base}\n\n{session_line(agent_id)}"


def reset() -> None:
    """Test helper."""
    _STATE.update({"cards": {}, "budgets": {}, "moods": {}, "round": 0, "hour": 12, "rng": random.Random(7),
                   "activity": {}})

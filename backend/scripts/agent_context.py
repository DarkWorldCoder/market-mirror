"""
MarketMirror: per-round persona cards for OASIS agents, plus the runtime speed knobs.

OASIS gives every agent the same generic instruction each round ("pick an action, don't just like").
That makes personas drift toward generic English and over-engagement. This module prepends a compact
persona card to every observation prompt: who they are, where they live, how people there write online,
their habits, and that scrolling past (do_nothing) is the normal outcome. It also gives each round a small
action budget and a mood, so activity varies the way it does for real people.

Install once per platform after the agent graph is built:

    from agent_context import install, begin_round
    install(agent_graph, config, seed=7, platform="twitter")   # patches SocialEnvironment.to_text_prompt (idempotent)
    ...
    begin_round(round_num, simulated_hour, platform="twitter")  # before env.step(...) each round

State is kept per platform (hour, budgets, moods), so a parallel Twitter + Reddit run does not have one
platform's begin_round overwrite the other's. Calls without a platform use the shared "default" slot,
which is what the single-platform scripts and the tests use.

Cards come from simulation_config.json: persona_index (name, segment, country, city, languages,
platform_habits, communities), agent_configs[].activity_level and community_config.

Speed knobs (environment variables, all optional):
    OASIS_MEMORY_WINDOW  messages of chat history each agent keeps in context (default 10). Without a
                         window camel re-tokenises the whole history before every call and then truncates
                         it to the model's max_tokens, which is what made long runs crawl.
    OASIS_TOKEN_LIMIT    context budget for that window, independent of max_tokens (default 32000).
    OASIS_SEMAPHORE      concurrent LLM calls per platform (default 50).
    OASIS_RECSYS         Twitter recommender: random (default, cheap) | twitter | twhin-bert (CPU model).
    OASIS_MAX_ITERATION  model/tool iterations per social action (default 3); bounds a stalled agent.
    OASIS_ACTION_TIMEOUT wall-time limit after an agent acquires a model slot (default 120 seconds, 480 through a
                         login gateway; without the variable it always stays above MODEL_TIMEOUT).
    OASIS_ACTIVE_AGENT_CAP optional maximum social actors selected per round (unset uses the scenario activity).
    MODEL_TIMEOUT        camel's per-call timeout in seconds (default 60 here, 420 through a login gateway;
                         camel's own default is 180).
"""

from __future__ import annotations

import json
import os
import random
import warnings
import asyncio
from typing import Any, Dict, List, Optional, Tuple

MOODS = ["relaxed", "bored", "in a hurry", "tired after work", "curious", "irritated by something earlier",
         "happy", "stressed about money", "distracted", "chatty"]
COMMENT_RATE = {0.0: "almost never", 0.3: "a few times a year", 0.5: "about once a month",
                0.7: "about once a week", 0.85: "a few times a week"}

DEFAULT_MEMORY_WINDOW = 10
DEFAULT_TOKEN_LIMIT = 32000
DEFAULT_SEMAPHORE = 50
DEFAULT_RECSYS = "random"
DEFAULT_MAX_ITERATION = 3
DEFAULT_ACTION_TIMEOUT = 120
DEFAULT_ACTIVE_AGENT_CAP = 0
DEFAULT_MODEL_TIMEOUT = 60
# a subscription gateway (backend/gateway/local_gateway.py over `claude -p` / `codex exec`) answers in 15-75 s but
# queues calls behind its workers and stops a call after about 210 s of running, so a call can take queue wait plus
# 210 s. camel's timeout must outlast that, or camel gives up and re-sends a call the gateway is still answering.
# The action limit wraps the model call, so it must be longer again.
GATEWAY_MODEL_TIMEOUT = 420
GATEWAY_ACTION_TIMEOUT = 480
ACTION_TIMEOUT_MARGIN = 60          # seconds an action limit keeps above the model timeout when not set explicitly


def via_local_gateway() -> bool:
    """True when the model is a local login gateway: the default port 5055, or any loopback URL when LLM_GATEWAY
    names a gateway backend (side-by-side gateways run on other ports)."""
    url = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_API_BASE_URL") or ""
    if any(h in url for h in ("127.0.0.1:5055", "localhost:5055")) or os.environ.get("LLM_API_KEY") == "gateway":
        return True
    return bool(os.environ.get("LLM_GATEWAY")) and any(h in url for h in ("://127.0.0.1:", "://localhost:"))


def _fresh(seed: int = 7) -> Dict[str, Any]:
    return {"cards": {}, "budgets": {}, "moods": {}, "round": 0, "hour": 12, "rng": random.Random(seed),
            "activity": {}, "occupations": {}, "behavior_states": {}, "personas": {}}


# One state dict per platform. "default" also carries the (global) environment-patch flag.
_PLATFORMS: Dict[str, Dict[str, Any]] = {"default": {**_fresh(), "installed": False}}
_STATE: Dict[str, Any] = _PLATFORMS["default"]


def _state(platform: Optional[str] = None) -> Dict[str, Any]:
    key = (platform or "default").lower()
    if key not in _PLATFORMS:
        _PLATFORMS[key] = _fresh()
    return _PLATFORMS[key]


def _rate_label(activity: float) -> str:
    label = "almost never"
    for threshold, text in sorted(COMMENT_RATE.items()):
        if activity >= threshold:
            label = text
    return label


def activity_levels(config: Dict[str, Any]) -> Dict[int, float]:
    """agent_id -> activity_level from agent_configs (0.5 when missing)."""
    return {int(a.get("agent_id")): float(a.get("activity_level") or 0.5)
            for a in (config or {}).get("agent_configs") or [] if isinstance(a, dict) and a.get("agent_id") is not None}


def persona_cards(config: Dict[str, Any]) -> Dict[int, str]:
    """agent_id -> card text. Graph actors (brand, companies) get a short organisation card."""
    cfg = config or {}
    index = [r for r in cfg.get("persona_index") or [] if isinstance(r, dict) and r.get("agent_id") is not None]
    activity = activity_levels(cfg)
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
                  activity: Optional[Dict[int, float]] = None,
                  occupation: str = "",
                  bstate: Optional[Dict[str, Any]] = None) -> Tuple[int, str]:
    """(action budget 1-3, mood) for one agent this round. More active people and evening hours get bigger budgets."""
    act = (activity if activity is not None else _STATE["activity"]).get(agent_id, 0.5)
    occ = (occupation or "").lower()
    if "night shift" in occ:
        peak = 1.0 if (0 <= hour <= 6 or 20 <= hour <= 23) else 0.45
    elif "student" in occ:
        peak = 1.0 if (13 <= hour <= 15 or 19 <= hour <= 23) else 0.65 if 8 <= hour <= 18 else 0.4
    else:
        peak = 1.0 if 18 <= hour <= 23 or 12 <= hour <= 13 else 0.7 if 7 <= hour <= 17 else 0.4
    x = rng.random() * act * peak
    budget = 3 if x > 0.55 else 2 if x > 0.25 else 1
    mood = rng.choice(MOODS)
    if 0 <= hour <= 5 and "night shift" not in occ:
        mood = rng.choice(["tired", "can't sleep", "bored"])
    if bstate:
        fat = float(bstate.get("fatigue", 0.0))
        tru = float(bstate.get("trust", 0.5))
        if fat >= 0.6:
            mood = "irritated by repeated ads"
            budget = max(1, budget - 1)
        elif tru <= 0.3:
            mood = "sceptical and guarded"
    return budget, mood


def context_updates(config_path: Optional[str], round_num: int) -> List[Dict[str, Any]]:
    """event_config.context_updates [{round?, text, source?}] from the live config file: the ones due by this round."""
    if not config_path:
        return []
    try:
        with open(config_path, encoding="utf-8") as f:
            ups = ((json.load(f).get("event_config") or {}).get("context_updates") or [])
    except (OSError, ValueError):
        return []
    out = []
    for u in ups:
        if not isinstance(u, dict) or not str(u.get("text") or "").strip():
            continue
        try:
            due = int(u.get("round")) if u.get("round") is not None else 0
        except (TypeError, ValueError):
            due = 0
        if due <= round_num:
            out.append({"round": due, "text": str(u["text"]).strip()[:400], "source": str(u.get("source") or "")[:60]})
    return out[-3:]                                           # the latest few matter; older news fades


def set_context(text: str, platform: Optional[str] = None) -> None:
    _state(platform)["context"] = [{"round": 0, "text": text, "source": ""}] if text else []


def begin_round(round_num: int, hour: int, platform: Optional[str] = None) -> None:
    """Refresh every agent's budget and mood for the coming round on this platform (deterministic for a seed),
    and pick up any context the operator pushed while the run is going (PUT /api/simulation/<sid>/context)."""
    st = _state(platform)
    rng = st["rng"]
    st["round"], st["hour"] = round_num, hour
    if st.get("config_path"):
        st["context"] = context_updates(st["config_path"], round_num)
        # tests run between rounds (feed, email, survey, pitch) update behavior_state.json: pick up fatigue/trust
        st["behavior_states"] = behavior_states(os.path.dirname(os.path.abspath(st["config_path"])))
    for aid in list(st["cards"]):
        st["budgets"][aid], st["moods"][aid] = round_flavour(
            aid, round_num, hour, rng, st["activity"],
            occupation=st["occupations"].get(aid, ""), bstate=st["behavior_states"].get(aid))


def occupations(config: Dict[str, Any]) -> Dict[int, str]:
    """agent_id -> occupation (or segment) from persona_index; shapes when in the day the person is online."""
    out: Dict[int, str] = {}
    for r in (config or {}).get("persona_index") or []:
        if isinstance(r, dict) and r.get("agent_id") is not None:
            occ = str(r.get("occupation") or r.get("segment") or "").strip()
            if occ:
                out[int(r["agent_id"])] = occ
    return out


def behavior_states(sim_dir: Optional[str], scope: str = "default") -> Dict[int, Dict[str, Any]]:
    """agent_id -> {fatigue, trust, ...} from the simulation's behavior_state.json (written by
    app/services/behavior_state.py when feed/email/survey/pitch tests run on this simulation). {} when absent."""
    if not sim_dir:
        return {}
    try:
        with open(os.path.join(sim_dir, "behavior_state.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    scopes = data.get("scopes") if isinstance(data, dict) else None
    agents = (scopes or {}).get(scope) or {}
    out: Dict[int, Dict[str, Any]] = {}
    for aid, rec in agents.items():
        try:
            st = rec.get("state") if isinstance(rec, dict) else None
            if isinstance(st, dict):
                out[int(aid)] = st
        except (TypeError, ValueError):
            continue
    return out


def session_line(agent_id: int, platform: Optional[str] = None) -> str:
    st = _state(platform)
    budget = st["budgets"].get(agent_id, 1)
    mood = st["moods"].get(agent_id, "relaxed")
    hour = st["hour"]
    line = (f"Right now it is about {hour:02d}:00 and you feel {mood}. You have time for at most {budget} "
            f"action(s) this session. If nothing deserves a reply, do_nothing.")
    ctx = st.get("context") or []
    if ctx:
        news = " ".join(f"{c['text']}" + (f" (via {c['source']})" if c.get("source") else "") for c in ctx)
        line = f"What people around you are saying today: {news}\n{line}"
    return line


def card_for(agent_id: int, platform: Optional[str] = None) -> str:
    return _state(platform)["cards"].get(agent_id, "")


def thought_for_action(
    agent_id: int,
    action_type: str,
    action_args: Optional[Dict[str, Any]] = None,
    platform: Optional[str] = None,
    agent_graph: Any = None,
) -> Tuple[str, str]:
    """Return (thought, mood) for an agent's social action. Extracts assistant reasoning from
    the agent's memory if present, else synthesizes an in-character BDE/mood inner monologue."""
    st = _state(platform)
    mood = str(st["moods"].get(agent_id, "relaxed"))
    args = action_args or {}
    # 1. Try extracting assistant reasoning from camel ChatHistoryMemory
    if agent_graph is not None:
        try:
            ag = agent_graph.get_agent(agent_id)
            mem = getattr(ag, "memory", None)
            recs = mem.retrieve() if mem is not None and hasattr(mem, "retrieve") else []
            for r in reversed(recs[-4:]):
                mr = getattr(r, "memory_record", r)
                role = getattr(getattr(mr, "role_at_backend", None), "value", getattr(mr, "role_at_backend", None))
                msg = getattr(mr, "message", None)
                txt = str(getattr(msg, "content", "") or "").strip()
                if role == "assistant" and txt and not txt.startswith("{"):
                    return txt[:240], mood
        except Exception:
            pass
    # 2. Grounded persona BDE + mood synthesis
    p = st.get("personas", {}).get(agent_id) or {}
    bde = p.get("bde") if isinstance(p.get("bde"), dict) else {}
    believes = str((bde.get("background") or {}).get("believes") or "").strip()
    who_asks = str((bde.get("decision_procedure") or {}).get("who_they_ask") or "").strip()
    stoppers = (bde.get("decision_procedure") or {}).get("stoppers") or []
    seg = p.get("segment") or p.get("occupation") or "viewer"
    act = (action_type or "").upper()
    if act == "CREATE_POST":
        thought = f"Feeling {mood}; sharing my honest view with my {seg} group" + (f" ({believes[:70]})" if believes else "") + "."
    elif act == "CREATE_COMMENT":
        thought = f"This caught my eye while {mood}; replying in my own words" + (f" — {believes[:60]}" if believes else "") + "."
    elif act == "QUOTE_POST":
        thought = f"Quoting this for my circle ({mood})" + (f"; I usually ask {who_asks} too" if who_asks else "") + "."
    elif act in ("LIKE_POST", "LIKE_COMMENT"):
        thought = f"Quick nod while scrolling ({mood}) — resonates with me, no need for a long comment."
    elif act in ("DISLIKE_POST", "DISLIKE_COMMENT"):
        stop_note = f" (triggers my stopper: {stoppers[0]})" if stoppers else ""
        thought = f"Feels off or pushy{stop_note}; downvoting and moving on."
    elif act == "DO_NOTHING":
        thought = f"Scrolling while {mood}; nothing here clears my bar" + (f" ({believes[:60]})" if believes else "") + "."
    else:
        thought = f"Acting while {mood} ({act.lower().replace('_', ' ')})."
    return thought, mood


def _agents_of(agent_graph: Any) -> List[Any]:
    try:
        agents = list(agent_graph.get_agents()) if hasattr(agent_graph, "get_agents") else []
    except Exception:  # noqa: BLE001 - graph shapes differ between OASIS versions
        agents = []
    return [item[1] if isinstance(item, tuple) else item for item in agents]


def install(agent_graph: Any, config: Dict[str, Any], seed: int = 7, platform: Optional[str] = None,
            memory_window: Optional[int] = None, token_limit: Optional[int] = None,
            config_path: Optional[str] = None) -> int:
    """Attach cards to the agents in `agent_graph`, tag them with their platform, bound their chat memory
    and patch SocialEnvironment.to_text_prompt once. Returns the number of agents that got a card.
    config_path: the live simulation_config.json, re-read every round for operator context updates."""
    st = _state(platform)
    st["cards"] = persona_cards(config)
    st["activity"] = activity_levels(config)
    st["personas"] = {
        int(r["agent_id"]): r
        for r in ((config or {}).get("persona_index") or [])
        if isinstance(r, dict) and r.get("agent_id") is not None
    }
    st["occupations"] = occupations(config)
    st["behavior_states"] = {}
    st["rng"] = random.Random(seed)
    st["config_path"] = config_path or (config or {}).get("_config_path")
    st["context"] = []
    begin_round(0, 12, platform)
    n = 0
    max_iterations = _env_int("OASIS_MAX_ITERATION", DEFAULT_MAX_ITERATION)
    for agent in _agents_of(agent_graph):
        aid = getattr(agent, "social_agent_id", None)
        if aid in st["cards"]:
            n += 1
        env = getattr(agent, "env", None)
        if platform and env is not None:
            try:
                env.mm_platform = platform
            except Exception:  # noqa: BLE001
                pass
        if hasattr(agent, "max_iteration"):
            agent.max_iteration = max_iterations
    memory_window_for(agent_graph, memory_window, token_limit)
    _patch_environment()
    return n


# ---------------------------------------------------------------------------------------------------
# Mixed providers: every person is played by the model that wrote them
# ---------------------------------------------------------------------------------------------------

def _pool_slots(env: Optional[Dict[str, str]] = None) -> List[Any]:
    """The provider slots of LLM_POOL (no network clients are built here)."""
    try:
        from app.utils.model_pool import MultiProviderPool
    except ImportError:  # pragma: no cover - the runner always has the backend on sys.path
        return []
    try:
        pool = MultiProviderPool.from_env(env=env, client_factory=lambda **kw: None)
    except Exception:  # noqa: BLE001 - a bad pool spec leaves the single model in place
        return []
    return list(pool.slots) if pool.is_multi else []


def _camel_model(slot: Any) -> Any:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    from app.utils.model_pool import provider_family
    cfg = {"max_tokens": 4096} if provider_family(slot.provider) == "claude" else None
    return ModelFactory.create(model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL, model_type=slot.model,
                               model_config_dict=cfg, url=slot.base_url, api_key=slot.api_key)


def assign_provider_models(agent_graph: Any, config: Dict[str, Any], env: Optional[Dict[str, str]] = None,
                           make_model: Any = None) -> Dict[str, int]:
    """With several providers in LLM_POOL, give every agent the model of the provider that wrote them
    (persona_index[].model_provider); agents without one (graph entities, community accounts) are spread evenly.
    Returns agents per provider, or {} when there is only one provider (the shared model stays)."""
    slots = _pool_slots(env)
    if not slots:
        return {}
    from app.utils.model_pool import provider_family
    try:
        from camel.models import ModelManager
    except ImportError:  # pragma: no cover
        ModelManager = None
    make = make_model or _camel_model
    models = [make(s) for s in slots]
    family = [provider_family(s.provider) for s in slots]
    writers = {int(r["agent_id"]): provider_family(r.get("model_provider"))
               for r in (config or {}).get("persona_index") or []
               if isinstance(r, dict) and r.get("agent_id") is not None}
    counts: Dict[str, int] = {}
    for agent in _agents_of(agent_graph):
        aid = getattr(agent, "social_agent_id", None)
        if aid is None:
            continue
        w = writers.get(int(aid))
        idx = family.index(w) if w in family else int(aid) % len(slots)
        backend = ModelManager(models[idx]) if ModelManager is not None else models[idx]
        try:
            agent.model_backend = backend
            agent.model_type = getattr(backend, "model_type", getattr(agent, "model_type", None))
            agent.mm_provider = slots[idx].provider
        except Exception:  # noqa: BLE001 - an agent that cannot be rebound keeps the shared model
            continue
        counts[slots[idx].provider] = counts.get(slots[idx].provider, 0) + 1
    return counts


# ---------------------------------------------------------------------------------------------------
# Speed knobs
# ---------------------------------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "") or default)
    except ValueError:
        v = default
    return v if v > 0 else default


def window_records(records: List[Any]) -> List[Any]:
    """Make a windowed chat history valid for the API: camel's window keeps the last N messages, which can
    start in the middle of a tool-call group. The Anthropic endpoint then rejects the request
    ("tool_call_id ... not found in tool_calls of previous message"). Keep the system message, start the
    window at the first user message after it, and drop tool results whose call is no longer there."""
    def role_of(r):
        mr = getattr(r, "memory_record", r)
        role = getattr(mr, "role_at_backend", None)
        return getattr(role, "value", role), getattr(getattr(mr, "message", None), "tool_call_id", None)

    out: List[Any] = []
    seen_calls = set()
    started = False
    for r in records:
        role, call_id = role_of(r)
        if role in ("system", "developer") and not out:
            out.append(r)
            continue
        if not started:
            if role != "user":
                continue
            started = True
        if role == "assistant" and call_id:
            seen_calls.add(call_id)
        elif role in ("function", "tool") and call_id and call_id not in seen_calls:
            continue
        out.append(r)
    return out if started else list(records)


def _patch_memory_window() -> None:
    """Wrap ChatHistoryMemory.retrieve once so windowed histories go through window_records."""
    if _STATE.get("window_patched"):
        return
    try:
        from camel.memories.agent_memories import ChatHistoryMemory
    except ImportError:  # pragma: no cover - only when camel is absent (tests)
        return
    original = ChatHistoryMemory.retrieve

    def retrieve(self):
        records = original(self)
        if getattr(self, "_window_size", None) is None:
            return records
        return window_records(records)

    ChatHistoryMemory.retrieve = retrieve
    _STATE["window_patched"] = True


def memory_window_for(agent_graph: Any, window: Optional[int] = None, token_limit: Optional[int] = None) -> int:
    """Give every agent's ChatHistoryMemory a sliding window and its context creator a token budget that
    does not depend on max_tokens. Returns the number of agents touched. Safe on graphs without camel agents."""
    window = window if window is not None else _env_int("OASIS_MEMORY_WINDOW", DEFAULT_MEMORY_WINDOW)
    token_limit = token_limit if token_limit is not None else _env_int("OASIS_TOKEN_LIMIT", DEFAULT_TOKEN_LIMIT)
    warnings.filterwarnings("ignore", message="Chat history window size limit")
    _patch_memory_window()
    n = 0
    for agent in _agents_of(agent_graph):
        mem = getattr(agent, "memory", None)
        if mem is None:
            continue
        touched = False
        if hasattr(mem, "_window_size"):
            mem._window_size = int(window)
            touched = True
        creator = mem.get_context_creator() if hasattr(mem, "get_context_creator") else None
        if creator is not None and hasattr(creator, "_token_limit"):
            creator._token_limit = int(token_limit)
            touched = True
        n += 1 if touched else 0
    return n


def semaphore_size() -> int:
    """Concurrent LLM calls per platform (OASIS_SEMAPHORE, default 50)."""
    return _env_int("OASIS_SEMAPHORE", DEFAULT_SEMAPHORE)


def active_agent_cap() -> int:
    return _env_int("OASIS_ACTIVE_AGENT_CAP", DEFAULT_ACTIVE_AGENT_CAP) or 2**31 - 1


def bound_llm_actions(env: Any, timeout_s: Optional[float] = None) -> float:
    """Bound each social agent after it acquires the OASIS semaphore.

    A single stalled agent otherwise keeps the whole env.step gather open.
    Interview actions use their separate request timeout and are untouched.
    """
    if getattr(env, "mm_action_timeout_installed", False):
        return env.mm_action_timeout_s
    seconds = timeout_s or _env_int("OASIS_ACTION_TIMEOUT", default_action_timeout())
    env.mm_action_timeouts = 0
    env.mm_action_timeout_s = seconds

    async def bounded(agent):
        async with env.llm_semaphore:
            try:
                return await asyncio.wait_for(agent.perform_action_by_llm(), timeout=seconds)
            except asyncio.TimeoutError:
                env.mm_action_timeouts += 1
                warnings.warn(f"social agent {getattr(agent, 'social_agent_id', '?')} timed out after {seconds}s")
                return None

    env._perform_llm_action = bounded
    env.mm_action_timeout_installed = True
    return seconds


def default_action_timeout() -> int:
    """The action limit when OASIS_ACTION_TIMEOUT is not set: 120 s (480 s through a login gateway), and always
    ACTION_TIMEOUT_MARGIN above the model timeout, so an action is not cut off while its model call may still answer
    (a MODEL_TIMEOUT override raises it too)."""
    base = GATEWAY_ACTION_TIMEOUT if via_local_gateway() else DEFAULT_ACTION_TIMEOUT
    try:
        model_s = float(os.environ.get("MODEL_TIMEOUT") or 0)
    except ValueError:
        model_s = 0.0
    return max(base, (int(model_s) + ACTION_TIMEOUT_MARGIN) if model_s > 0 else 0)


def model_timeout() -> float:
    """Set camel's MODEL_TIMEOUT default (60 s, 420 s through a login gateway) unless the environment already chose
    one; returns the value."""
    os.environ.setdefault("MODEL_TIMEOUT", str(GATEWAY_MODEL_TIMEOUT if via_local_gateway() else DEFAULT_MODEL_TIMEOUT))
    try:
        return float(os.environ["MODEL_TIMEOUT"])
    except ValueError:
        os.environ["MODEL_TIMEOUT"] = str(DEFAULT_MODEL_TIMEOUT)
        return float(DEFAULT_MODEL_TIMEOUT)


def recsys_type() -> str:
    """Twitter recommender name (OASIS_RECSYS): random (default), twitter or twhin-bert."""
    v = (os.environ.get("OASIS_RECSYS") or DEFAULT_RECSYS).strip().lower()
    return v if v in ("random", "twitter", "twhin-bert") else DEFAULT_RECSYS


def twitter_platform(db_path: str) -> Any:
    """A Twitter Platform like oasis.make(DefaultPlatformType.TWITTER) builds, but with the recommender
    chosen by OASIS_RECSYS instead of the hard-coded twhin-bert. Returns None when OASIS is absent."""
    try:
        from oasis.social_platform.channel import Channel
        from oasis.social_platform.platform import Platform
    except ImportError:  # pragma: no cover - only when OASIS is absent (tests)
        return None
    return Platform(db_path=db_path, channel=Channel(), recsys_type=recsys_type(),
                    refresh_rec_post_count=2, max_rec_post_len=2, following_post_count=3)


# ---------------------------------------------------------------------------------------------------

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
        return compose_prompt(getattr(getattr(self, "action", None), "agent_id", None), base,
                              getattr(self, "mm_platform", None))

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


def compose_prompt(agent_id: Optional[int], base: str, platform: Optional[str] = None) -> str:
    """Card + original observation + session line. Pure, so it is unit-testable without OASIS."""
    st = _state(platform)
    if agent_id is None or agent_id not in st["cards"]:
        return base
    return f"{st['cards'][agent_id]}\n\n{base}\n\n{session_line(agent_id, platform)}"


def reset() -> None:
    """Test helper: forget every platform's cards, budgets and moods (keeps the patch flag)."""
    for key in list(_PLATFORMS):
        if key != "default":
            del _PLATFORMS[key]
    _STATE.update(_fresh())

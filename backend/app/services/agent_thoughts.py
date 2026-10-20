"""
agent_thoughts.py - Real Agent Cognitive Stream & Inner-Monologue Simulation Engine.

Captures, harvests, and simulates the private cognitive stream of every persona across:
  1. System 1 (Fast Gut Impulse): immediate emotional/attentional reaction in native slang/voice
  2. System 2 (BDE Deliberation): wallet budget check, dealbreaker scan, social consultation
  3. Private Thought vs Public Action (Say-vs-Do Divergence): when an agent thinks one thing
     privately (e.g., curious or polite) but does another publicly (scrolls past, abandons form,
     or hides the ad).

Works across:
  - Live stimulus thought simulations (`run_thought_simulation`)
  - Full-run multi-touchpoint thought harvesting (`harvest_thoughts`) from OASIS social actions,
    feed scroll sessions, landing-page friction gates, sales pitches, email tests, website tests,
    and surveys.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils.logger import get_logger
from .feed_test import UsageMeter, _llm_json, _num

logger = get_logger("mirofish.agent_thoughts")

THOUGHT_SYSTEM = (
    "You are simulating the real, unfiltered internal monologue of a specific person in their daily life. "
    "You are NOT a marketing assistant. Think in first person ('I...'), using the person's natural local "
    "phrasing, concerns, money habits, and scepticism. Distinguish clearly between their fast gut reaction "
    "(System 1), their practical wallet/dealbreaker check (System 2), and what they actually do publicly. "
    "Return only valid JSON."
)

GUT_TAGS = (
    "curious",
    "skeptical",
    "price_shock",
    "ad_fatigue",
    "social_proof",
    "trust_signal",
    "habitual_ignore",
    "urgent_need",
)

ROADBLOCK_TAGS = (
    "none",
    "price_vs_wallet",
    "card_trap_fear",
    "scam_skepticism",
    "family_approval_needed",
    "no_urgent_need",
    "page_or_form_friction",
)


def _classify_gut(thought: str, action: str = "", sentiment: str = "") -> str:
    low = f"{thought} {action} {sentiment}".lower()
    if any(w in low for w in ("scam", "fake", "catch", "trap", "doubt", "suspicious", "too good", "skeptic", "sceptic", "dhokha", "feki")):
        return "skeptical"
    if any(w in low for w in ("expensive", "price", "cost", "afford", "tight", "budget", "paisa", "mahal", "rupees", "npr", "rs ", "$")):
        return "price_shock"
    if any(w in low for w in ("again", "another ad", "spam", "tired of", "annoying", "hide", "everywhere", "seen this")):
        return "ad_fatigue"
    if any(w in low for w in ("friend", "comments", "reviews", "cousin", "sister", "husband", "wife", "group", "people say")):
        return "social_proof"
    if any(w in low for w in ("verified", "no card", "offline", "clear", "honest", "legit", "safe")):
        return "trust_signal"
    if any(w in low for w in ("interesting", "useful", "try", "check", "nice", "good", "helpful", "need this", "accha", "ramro")):
        return "curious"
    return "habitual_ignore"


def _classify_roadblock(thought: str, drop_reason: str = "", gate: str = "") -> str:
    low = f"{thought} {drop_reason} {gate}".lower()
    if gate == "wallet_limit" or any(w in low for w in ("exceeds", "budget", "afford", "expensive", "price", "paisa", "tight")):
        return "price_vs_wallet"
    if any(w in low for w in ("card", "auto-renew", "autorenew", "subscription", "charged")):
        return "card_trap_fear"
    if any(w in low for w in ("scam", "fake", "trust", "spam", "phishing", "agent")):
        return "scam_skepticism"
    if any(w in low for w in ("ask my", "wife", "husband", "parents", "father", "mother", "sister", "brother", "family")):
        return "family_approval_needed"
    if gate in ("network_timeout", "form_abandon") or any(w in low for w in ("phone number", "slow", "load", "form", "otp", "steps")):
        return "page_or_form_friction"
    if any(w in low for w in ("don't need", "later", "busy", "not now", "scroll")):
        return "no_urgent_need"
    return "none"


def synthesize_social_thought(
    person: Dict[str, Any],
    action_type: str,
    action_args: Dict[str, Any],
    mood: str = "relaxed",
) -> str:
    """Deterministic, persona-grounded inner monologue fallback when a social trace row has no raw LLM thought."""
    name = person.get("name") or "I"
    seg = person.get("segment") or person.get("occupation") or "viewer"
    bde = person.get("bde") if isinstance(person.get("bde"), dict) else {}
    believes = ((bde.get("background") or {}).get("believes") or "").strip()
    who_asks = ((bde.get("decision_procedure") or {}).get("who_they_ask") or "").strip()
    stoppers = (bde.get("decision_procedure") or {}).get("stoppers") or []
    content = str(action_args.get("content") or action_args.get("quote_content") or action_args.get("post_content") or "").strip()
    snippet = (content[:80] + "…") if len(content) > 80 else content

    act = (action_type or "").upper()
    if act == "CREATE_POST":
        return f"Feeling {mood}; sharing what's on my mind with my {seg} circle" + (f" ({believes[:70]})" if believes else "") + "."
    if act == "CREATE_COMMENT":
        return f"This caught my attention ({mood}). Wanted to chime in directly" + (f" — {believes[:60]}" if believes else "") + "."
    if act == "QUOTE_POST":
        return f"Adding my own take for people I know" + (f"; I usually check with {who_asks} on things like this" if who_asks else "") + "."
    if act == "REPOST":
        return f"Worth passing along to my feed while I'm {mood}."
    if act == "LIKE_POST" or act == "LIKE_COMMENT":
        return f"Quick nod while scrolling ({mood}) — agrees with how I see it, no need to write a long reply."
    if act == "DISLIKE_POST" or act == "DISLIKE_COMMENT":
        stopper_note = f" (reminds me of {stoppers[0]})" if stoppers else ""
        return f"Feels pushy or off-target{stopper_note}; downvoting and moving on."
    if act == "MUTE":
        return "Too much noise in my feed; muting this account."
    if act == "FOLLOW":
        return "Looks relevant to my group; following to see if they stay useful."
    return f"Scrolling while {mood}" + (f" — nothing here beats my usual rule ({believes[:60]})" if believes else ", scrolling past") + "."


def harvest_thoughts(sim_dir: str) -> Dict[str, Any]:
    """
    Collect and unify all agent thoughts across every touchpoint in a simulation directory:
    - Social simulation (`twitter/actions.jsonl`, `reddit/actions.jsonl`)
    - Ad feed scroll & landing page (`feed_test.json`)
    - Sales pitch (`pitch.json`)
    - Email sequence (`email_test.json`)
    - Survey (`survey.json`)
    - Website test (`website_test.json`)
    - Dedicated thought lab (`thought_stream.json`)
    """
    def _load(rel: str) -> Any:
        p = os.path.join(sim_dir, rel)
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    cfg = _load("simulation_config.json") or {}
    index = {
        int(r["agent_id"]): r
        for r in (cfg.get("persona_index") or [])
        if isinstance(r, dict) and r.get("agent_id") is not None
    }
    bstate_raw = _load("behavior_state.json") or {}
    scopes = bstate_raw.get("scopes") or {}
    default_scope = scopes.get("default") or (next(iter(scopes.values())) if scopes else {})

    items: List[Dict[str, Any]] = []

    def _person_meta(aid: Any, fallback_name: str = "", fallback_seg: str = "", fallback_country: str = "", fallback_prov: str = "") -> Dict[str, Any]:
        try:
            aid_int = int(aid) if aid is not None else -1
        except (TypeError, ValueError):
            aid_int = -1
        p = index.get(aid_int) or {}
        prov_raw = p.get("provenance")
        prov_type = "real_intake" if "real_intake" in str((prov_raw.get("profile") if isinstance(prov_raw, dict) else prov_raw) or "") else "synthetic"
        st = (default_scope.get(str(aid_int)) or {}).get("state") or {}
        return {
            "agent_id": aid_int if aid_int >= 0 else None,
            "name": p.get("name") or fallback_name or f"Agent {aid}",
            "segment": p.get("segment") or fallback_seg or "",
            "country": p.get("country") or fallback_country or "",
            "age": p.get("age"),
            "occupation": p.get("occupation") or "",
            "life_stage": p.get("life_stage") or "",
            "payday_status": p.get("payday_status") or "",
            "model_provider": fallback_prov or p.get("model_provider") or "claude",
            "provenance": prov_type,
            "mood": st.get("mood") or "neutral",
            "trust": st.get("trust", 0.5),
            "fatigue": st.get("fatigue", 0.0),
            "bde": p.get("bde") if isinstance(p.get("bde"), dict) else {},
        }

    # 1. Dedicated thought lab (`thought_stream.json`)
    t_lab = _load("thought_stream.json")
    if isinstance(t_lab, dict):
        for row in t_lab.get("entries") or []:
            if not isinstance(row, dict) or not row.get("thought"):
                continue
            meta = _person_meta(row.get("agent_id"), row.get("name", ""), row.get("segment", ""), row.get("country", ""), row.get("model_provider", ""))
            items.append({
                **meta,
                "touchpoint": "thought_lab",
                "stimulus": row.get("stimulus") or t_lab.get("stimulus") or "Campaign stimulus",
                "thought": str(row.get("thought") or ""),
                "system2_deliberation": str(row.get("system2_deliberation") or ""),
                "public_action": str(row.get("public_action") or ""),
                "system1_gut": str(row.get("system1_gut") or _classify_gut(str(row.get("thought") or ""))),
                "mental_roadblock": str(row.get("mental_roadblock") or _classify_roadblock(str(row.get("thought") or ""))),
                "conviction": row.get("conviction_0_10"),
                "diverged": bool(row.get("diverged")),
            })

    # 2. Feed Test scroll thoughts & Landing Page thoughts (`feed_test.json`)
    ft = _load("feed_test.json")
    if isinstance(ft, dict):
        creatives = {c.get("id"): c for c in (ft.get("creatives") or []) if isinstance(c, dict)}
        for s in ft.get("sessions") or []:
            if not isinstance(s, dict):
                continue
            ad = s.get("ad") or {}
            thought = str(ad.get("thought") or "").strip()
            cid = s.get("creative_id") or ""
            c_info = creatives.get(cid) or {}
            stim = f"{s.get('platform', 'feed').title()} ad {cid}: {c_info.get('headline') or c_info.get('text', '')[:60]}"
            meta = _person_meta(s.get("agent_id"), s.get("name", ""), s.get("segment", ""), s.get("country", ""), s.get("model_provider", ""))
            if thought and thought.lower() != "scroll":
                clicked = bool(ad.get("click"))
                stopped = bool(ad.get("stopped"))
                hidden = bool(ad.get("hide"))
                comment = str(ad.get("comment") or "").strip()
                if hidden:
                    pub = "Hid ad"
                elif clicked:
                    pub = f"Clicked ad ({cid})" + (f' & commented "{comment[:50]}"' if comment else "")
                elif comment:
                    pub = f'Commented "{comment[:60]}" (no click)'
                elif stopped:
                    pub = f"Paused {ad.get('dwell', 2)}s, then scrolled past"
                else:
                    pub = "Scrolled past"
                gut = _classify_gut(thought, pub)
                diverged = (gut == "curious" and not clicked) or (clicked and bool((s.get("landing") or {}).get("drop_reason")))
                items.append({
                    **meta,
                    "touchpoint": "ad_scroll",
                    "stimulus": stim,
                    "thought": thought,
                    "system2_deliberation": f"Ad avoidance {(meta['bde'].get('decision_procedure') or {}).get('risk', 'normal')}; budget {(meta['bde'].get('evaluation') or {}).get('monthly_discretionary', 'standard')}",
                    "public_action": pub,
                    "system1_gut": gut,
                    "mental_roadblock": _classify_roadblock(thought),
                    "conviction": round(float(ad.get("p_click") or (0.7 if clicked else 0.2)) * 10, 1),
                    "diverged": diverged,
                })
            land = s.get("landing") or {}
            l_thought = str(land.get("thought") or land.get("drop_reason") or "").strip()
            if l_thought:
                conv = bool(land.get("completed"))
                gate = str(land.get("friction_gate") or ("completed" if conv else "form_abandon"))
                drop = str(land.get("drop_reason") or "")
                pub_l = "Completed landing form (Converted)" if conv else f"Abandoned landing page ({gate}: {drop[:70]})"
                items.append({
                    **meta,
                    "touchpoint": "landing_page",
                    "stimulus": f"Landing page after clicking {cid}",
                    "thought": l_thought,
                    "system2_deliberation": drop or "Checked form fields and price against BDE rules",
                    "public_action": pub_l,
                    "system1_gut": "trust_signal" if conv else _classify_gut(l_thought, drop),
                    "mental_roadblock": "none" if conv else _classify_roadblock(l_thought, drop, gate),
                    "conviction": 8.5 if conv else 2.5,
                    "diverged": not conv,  # Clicked the ad with interest, then backed out on the page
                })

    # 3. Sales Pitch (`pitch.json`)
    pitch = _load("pitch.json")
    if isinstance(pitch, dict):
        for p in pitch.get("people") or []:
            if not isinstance(p, dict):
                continue
            meta = _person_meta(p.get("agent_id"), p.get("name", ""), p.get("segment", ""), p.get("country", ""), p.get("model_provider", ""))
            t1 = p.get("turn1") or {}
            t2 = p.get("turn2") or {}
            thought = str(t2.get("thought") or t1.get("thought") or t1.get("objection") or "").strip()
            reply = str(t2.get("reply") or t1.get("reply") or "").strip()
            verdict = str(p.get("final_verdict") or t1.get("verdict") or "maybe").lower()
            if thought or reply:
                inner = thought or f"Weighing pitch: {reply[:120]}"
                pub = f"Verdict: {verdict.upper()} — Said: \"{reply[:90]}\""
                diverged = ("polite" in inner.lower() or "maybe" in verdict) and verdict != "yes"
                items.append({
                    **meta,
                    "touchpoint": "sales_pitch",
                    "stimulus": "1-on-1 Sales Pitch & Rebuttal",
                    "thought": inner,
                    "system2_deliberation": str(t1.get("objection") or p.get("what_would_close") or ""),
                    "public_action": pub,
                    "system1_gut": _classify_gut(inner, reply, verdict),
                    "mental_roadblock": _classify_roadblock(inner, str(t1.get("objection") or "")),
                    "conviction": round(float(p.get("lead_score") or 50) / 10.0, 1),
                    "diverged": diverged,
                })

    # 4. Survey (`survey.json`)
    survey = _load("survey.json")
    if isinstance(survey, dict):
        for r in (survey.get("responses") or [])[:80]:
            if not isinstance(r, dict) or not isinstance(r.get("answer"), dict):
                continue
            ans = r["answer"]
            thought = str(ans.get("first_thought") or ans.get("reasoning") or ans.get("main_objection") or "").strip()
            if not thought:
                continue
            meta = _person_meta(r.get("agent_id"), r.get("name", ""), r.get("segment", ""), r.get("country", ""), r.get("model_provider", ""))
            verdict = str(ans.get("would_convert") or "maybe").lower()
            obj = str(ans.get("main_objection") or "").strip()
            conv_me = str(ans.get("what_would_convince_me") or "").strip()
            pub = f"Survey verdict: {verdict.upper()} (intent {ans.get('purchase_intent', '–')}/5)"
            diverged = verdict in ("yes", "maybe") and bool(obj) and _classify_roadblock(obj) != "none"
            items.append({
                **meta,
                "touchpoint": "survey",
                "stimulus": str(survey.get("offer") or "Buyer Survey"),
                "thought": thought,
                "system2_deliberation": f"Objection: {obj}" + (f" · Needs: {conv_me}" if conv_me else ""),
                "public_action": pub,
                "system1_gut": _classify_gut(thought, obj),
                "mental_roadblock": _classify_roadblock(thought, obj),
                "conviction": round(float(ans.get("purchase_intent") or 2.5) * 2.0, 1),
                "diverged": diverged,
            })

    # 5. Social Simulation Actions (`twitter/actions.jsonl`, `reddit/actions.jsonl`)
    for plat in ("twitter", "reddit"):
        act_path = os.path.join(sim_dir, plat, "actions.jsonl")
        if not os.path.exists(act_path):
            continue
        try:
            with open(act_path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        social_added = 0
        for line in lines:
            if social_added >= 60:
                break
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("event_type"):
                continue
            act_type = str(row.get("action_type") or "").upper()
            if act_type in ("REFRESH", "SIGN_UP", ""):
                continue
            aid = row.get("agent_id")
            args = row.get("action_args") if isinstance(row.get("action_args"), dict) else {}
            meta = _person_meta(aid, row.get("agent_name", ""))
            raw_thought = str(row.get("thought") or args.get("thought") or "").strip()
            mood = str(row.get("mood") or meta.get("mood") or "relaxed")
            if not raw_thought:
                raw_thought = synthesize_social_thought(index.get(int(aid)) if isinstance(aid, int) and aid in index else meta, act_type, args, mood)
            content = str(args.get("content") or args.get("quote_content") or args.get("post_content") or "").strip()
            pub = f"{plat.title()} {act_type}" + (f': "{content[:80]}"' if content else "")
            items.append({
                **meta,
                "touchpoint": "social_feed",
                "stimulus": f"{plat.title()} Round {row.get('round', '?')}",
                "thought": raw_thought,
                "system2_deliberation": f"Mood: {mood} · Trust: {meta.get('trust', 0.5):.2f}",
                "public_action": pub,
                "system1_gut": _classify_gut(raw_thought, content),
                "mental_roadblock": _classify_roadblock(raw_thought),
                "conviction": 7.0 if act_type in ("CREATE_POST", "CREATE_COMMENT", "QUOTE_POST") else 4.0,
                "diverged": act_type == "DO_NOTHING" and "curious" in raw_thought.lower(),
            })
            social_added += 1

    return summarize_thoughts(items)


def summarize_thoughts(entries: List[Dict[str, Any]], stimulus: str = "") -> Dict[str, Any]:
    """Compute cohort-level cognitive summary metrics over a list of thought entries."""
    guts = Counter(e.get("system1_gut") or "habitual_ignore" for e in entries)
    blocks = Counter(e.get("mental_roadblock") or "none" for e in entries if (e.get("mental_roadblock") or "none") != "none")
    touchpoints = Counter(e.get("touchpoint") or "other" for e in entries)
    provs = Counter(str(e.get("model_provider") or "claude").lower() for e in entries)
    diverged_count = sum(1 for e in entries if e.get("diverged"))
    convictions = [float(e["conviction"]) for e in entries if e.get("conviction") is not None]
    avg_conv = round(sum(convictions) / len(convictions), 2) if convictions else None

    by_seg: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in entries:
        if e.get("segment"):
            by_seg[str(e["segment"])].append(e)

    seg_summary = []
    for seg, rows in sorted(by_seg.items(), key=lambda kv: -len(kv[1])):
        s_guts = Counter(r.get("system1_gut") or "habitual_ignore" for r in rows)
        s_blocks = Counter(r.get("mental_roadblock") or "none" for r in rows if (r.get("mental_roadblock") or "none") != "none")
        s_div = sum(1 for r in rows if r.get("diverged"))
        seg_summary.append({
            "segment": seg,
            "count": len(rows),
            "top_gut": s_guts.most_common(1)[0][0] if s_guts else "neutral",
            "top_roadblock": s_blocks.most_common(1)[0][0] if s_blocks else "none",
            "divergence_pct": round(100.0 * s_div / len(rows), 1) if rows else 0.0,
        })

    return {
        "generated_at": datetime.now().isoformat(),
        "stimulus": stimulus,
        "total_thoughts": len(entries),
        "unique_agents": len({e.get("agent_id") or e.get("name") for e in entries}),
        "divergence_count": diverged_count,
        "divergence_rate_pct": round(100.0 * diverged_count / len(entries), 1) if entries else 0.0,
        "avg_conviction": avg_conv,
        "dominant_gut": guts.most_common(1)[0][0] if guts else "none",
        "top_roadblock": blocks.most_common(1)[0][0] if blocks else "none",
        "gut_breakdown": dict(guts.most_common()),
        "roadblock_breakdown": dict(blocks.most_common()),
        "by_touchpoint": dict(touchpoints.most_common()),
        "by_provider": dict(provs.most_common()),
        "by_segment": seg_summary,
        "entries": entries[:200],
    }


def _thought_prompt(person: Dict[str, Any], stimulus: Dict[str, Any]) -> str:
    bde = person.get("bde") if isinstance(person.get("bde"), dict) else {}
    bg = bde.get("background") or {}
    dp = bde.get("decision_procedure") or {}
    ev = bde.get("evaluation") or {}
    headline = stimulus.get("headline") or stimulus.get("title") or ""
    text = stimulus.get("text") or stimulus.get("offer") or stimulus.get("prompt") or ""
    price = stimulus.get("price") or "not stated"
    channel = stimulus.get("channel") or stimulus.get("platform") or "social feed"

    return (
        f"Who you are:\n{person.get('persona', '')[:1200]}\n"
        f"(Name: {person.get('name')}, Age: {person.get('age')}, City: {person.get('city', '')}, "
        f"Country: {person.get('country', '')}, Segment: {person.get('segment', '')})\n"
        f"Your beliefs: {bg.get('believes', 'cautious with new offers')}\n"
        f"Say-vs-Do habit: {bg.get('says_vs_does', 'polite in conversation, strict with wallet')}\n"
        f"Monthly discretionary budget: {ev.get('monthly_discretionary', 'limited')} · Payday status: {person.get('payday_status', 'mid_month')}\n"
        f"Dealbreakers: {', '.join(ev.get('dealbreakers') or dp.get('stoppers') or ['hidden fees'])}\n"
        f"Who you consult before buying: {dp.get('who_they_ask', 'nobody')}\n\n"
        f"You just encountered this on {channel}:\n"
        f"Headline: {headline}\n"
        f"Message / Offer: {text}\n"
        f"Price: {price}\n\n"
        "Simulate your real internal cognitive stream step-by-step:\n"
        "1. `thought`: Your unfiltered first-person inner monologue (1-2 sentences in your natural voice/slang).\n"
        "2. `system1_gut`: One of `curious|skeptical|price_shock|ad_fatigue|social_proof|trust_signal|habitual_ignore|urgent_need`.\n"
        "3. `system2_deliberation`: How your wallet budget, dealbreakers, or family consultation rule applies right now.\n"
        "4. `mental_roadblock`: One of `none|price_vs_wallet|card_trap_fear|scam_skepticism|family_approval_needed|no_urgent_need|page_or_form_friction`.\n"
        "5. `private_verdict`: `yes|maybe|no` (how you privately feel).\n"
        "6. `public_action`: What you actually do outwardly (e.g. `Scrolled past without clicking`, `Clicked to check price, left at card step`, `Screenshotted to send to sister`, `Signed up`).\n"
        "7. `conviction_0_10`: Number from 0 to 10.\n"
        'Return JSON: {"thought": "...", "system1_gut": "...", "system2_deliberation": "...", '
        '"mental_roadblock": "...", "private_verdict": "maybe", "public_action": "...", "conviction_0_10": 4.5}'
    )


def run_thought_simulation(
    client: Any,
    model: str,
    stimulus: Any,
    people: List[Dict[str, Any]],
    max_personas: int = 40,
    parallel: int = 8,
    seed: int = 7,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """
    Run a live multi-agent cognitive inner-monologue simulation on a marketing stimulus.
    Distributes calls across MultiProviderPool when configured.
    """
    if isinstance(stimulus, str):
        stim_dict = {"text": stimulus.strip(), "headline": "", "price": "not stated", "channel": "social feed"}
    elif isinstance(stimulus, dict):
        stim_dict = {
            "headline": str(stimulus.get("headline") or stimulus.get("title") or "").strip(),
            "text": str(stimulus.get("text") or stimulus.get("offer") or stimulus.get("prompt") or "").strip(),
            "price": str(stimulus.get("price") or "not stated").strip(),
            "channel": str(stimulus.get("channel") or stimulus.get("platform") or "social feed").strip(),
        }
    else:
        raise ValueError("stimulus must be a string or object")
    if not stim_dict.get("text") and not stim_dict.get("headline"):
        raise ValueError("stimulus requires text, offer, or headline")

    rng = random.Random(seed)
    cohort = list(people)
    if len(cohort) > max_personas:
        cohort = rng.sample(cohort, max_personas)

    meter = client if isinstance(client, UsageMeter) else UsageMeter(client)
    client = meter
    done_lock = threading.Lock()
    done_count = 0

    def _one(person: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal done_count
        aid = person.get("agent_id")
        prompt = _thought_prompt(person, stim_dict)
        try:
            data, prov, mod = _llm_json(
                client, model, THOUGHT_SYSTEM, prompt,
                temperature=0.7, max_tokens=700, agent_id=aid, return_meta=True
            )
            if not isinstance(data, dict):
                data = {}
        except Exception as e:
            logger.warning(f"thought simulation failed for {person.get('name')}: {e}")
            data, prov, mod = {}, person.get("model_provider") or "claude", model

        with done_lock:
            done_count += 1
            if progress:
                progress(done_count, len(cohort), f"Simulated thought {done_count}/{len(cohort)}")

        thought = str(data.get("thought") or "").strip() or synthesize_social_thought(person, "DO_NOTHING", {}, "curious")
        gut = str(data.get("system1_gut") or "").strip().lower()
        if gut not in GUT_TAGS:
            gut = _classify_gut(thought)
        roadblock = str(data.get("mental_roadblock") or "").strip().lower()
        if roadblock not in ROADBLOCK_TAGS:
            roadblock = _classify_roadblock(thought, str(data.get("system2_deliberation") or ""))
        priv = str(data.get("private_verdict") or "maybe").strip().lower()
        pub = str(data.get("public_action") or "Scrolled past").strip()
        conv = round(_num(data.get("conviction_0_10"), 0.0, 10.0), 1)
        diverged = (priv in ("yes", "maybe") and any(w in pub.lower() for w in ("scroll", "left", "abandon", "ignore", "back out", "wait"))) or (gut == "curious" and roadblock != "none")
        prov_raw = person.get("provenance")
        prov_type = "real_intake" if "real_intake" in str((prov_raw.get("profile") if isinstance(prov_raw, dict) else prov_raw) or "") else "synthetic"
        return {
            "agent_id": aid,
            "name": person.get("name") or f"Agent {aid}",
            "segment": person.get("segment") or "",
            "country": person.get("country") or "",
            "age": person.get("age"),
            "occupation": person.get("occupation") or "",
            "model_provider": person.get("model_provider") or prov or "claude",
            "model_name": person.get("model_name") or mod or model,
            "provenance": prov_type,
            "touchpoint": "thought_lab",
            "stimulus": stim_dict.get("headline") or stim_dict.get("text")[:80],
            "thought": thought,
            "system1_gut": gut,
            "system2_deliberation": str(data.get("system2_deliberation") or "").strip(),
            "mental_roadblock": roadblock,
            "private_verdict": priv,
            "public_action": pub,
            "conviction": conv,
            "conviction_0_10": conv,
            "diverged": diverged,
        }

    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(cohort) or 1))) as pool:
        entries = list(pool.map(_one, cohort))

    stim_label = f"{stim_dict.get('headline')}: {stim_dict.get('text')}" if stim_dict.get("headline") else stim_dict.get("text", "")
    res = summarize_thoughts(entries, stimulus=stim_label[:200])
    res["usage"] = meter.snapshot()
    return res

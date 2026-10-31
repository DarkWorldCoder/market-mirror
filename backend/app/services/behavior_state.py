"""What each simulated person has been through: a small, persistent behaviour state and an episodic memory.

Every test leaves traces: the feed test (saw the ad, stopped, clicked, hid it, commented), the email test (opened,
clicked, unsubscribed), the survey (said maybe, objected to the card step) and the sales pitch (objection, verdict).
Later tests read them back, so the person answering the survey is the one who scrolled past the ad twice, and the
person hearing the pitch is the one who already said the card step feels like a scam.

Design rules (see docs/HUMAN_BEHAVIOR_RESEARCH.md, "Proposed behavior model"):
- Memories are only what the simulation actually showed or did to that person, each with its test and source id.
- State changes by declared transition rules, nothing hidden: familiarity and fatigue grow with exposure, trust in
  the brand moves with what the person did (click/open +, hide/spam/unsubscribe -), all clamped to [0, 1].
- Scopes keep runs apart: every record and read names a scope (a run, or a study cell), so a control cell never
  reads a treatment cell's memories.
- Synthetic and simulated, always: these are simulation events, never observations of a real customer.
- Feelings (version 2): an event may carry the model's appraisal ("feel"); emotion.py turns it into one emotion and moves
  a mood that fades back to the person's baseline over simulated hours. Mode "off" leaves all of this out.
"""

import json
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

from . import emotion

STATE_FILE = "behavior_state.json"
MAX_MEMORIES = 30
_LOCK = threading.Lock()

# kind -> (familiarity delta, fatigue delta, trust delta)
TRANSITIONS = {
    "saw_ad": (0.10, 0.08, 0.0), "stopped_on_ad": (0.10, 0.04, 0.02), "clicked_ad": (0.10, 0.0, 0.06),
    "reacted_to_ad": (0.05, 0.0, 0.03), "commented_on_ad": (0.08, 0.0, 0.0), "hid_ad": (0.05, 0.10, -0.15),
    "received_email": (0.05, 0.05, 0.0), "opened_email": (0.08, 0.0, 0.03), "clicked_email": (0.08, 0.0, 0.06),
    "replied_email": (0.08, 0.0, 0.04), "unsubscribed": (0.0, 0.15, -0.20), "marked_spam": (0.0, 0.2, -0.30),
    "answered_survey": (0.05, 0.02, 0.0), "objected": (0.0, 0.0, -0.05), "heard_pitch": (0.08, 0.05, 0.0),
    "agreed_next_step": (0.05, 0.0, 0.08), "declined": (0.0, 0.05, -0.05), "posted": (0.03, 0.0, 0.0),
    "saw_brand_post": (0.08, 0.04, 0.0), "replied_to_brand_post": (0.06, 0.0, 0.02),
    "abandoned_price": (0.05, 0.06, -0.08), "abandoned_dealbreaker": (0.05, 0.08, -0.12),
    "switched_competitor": (0.05, 0.05, -0.10), "landed_page": (0.02, 0.02, 0.0), "walked_away": (0.0, 0.05, -0.03),
}


def _path(sim_dir: str) -> str:
    return os.path.join(sim_dir, STATE_FILE)


def load(sim_dir: str) -> Dict[str, Any]:
    try:
        with open(_path(sim_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"version": 1, "scopes": {}}
    except (OSError, ValueError):
        return {"version": 1, "scopes": {}}


def _save(sim_dir: str, data: Dict[str, Any]) -> None:
    tmp = _path(sim_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _path(sim_dir))


def _agent(data: Dict[str, Any], scope: str, agent_id: Any) -> Dict[str, Any]:
    sc = data.setdefault("scopes", {}).setdefault(scope or "default", {})
    return sc.setdefault(
        str(agent_id),
        {
            "state": {"familiarity": 0.0, "fatigue": 0.0, "trust": 0.5, "mood": "neutral", "energy": 0.7, "wallet_pressure": 0.3},
            "memory": [],
            "trajectory": [],
        },
    )


def _clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 3)


def _derive_mood(st: Dict[str, Any]) -> str:
    fat = float(st.get("fatigue", 0.0))
    tru = float(st.get("trust", 0.5))
    fam = float(st.get("familiarity", 0.0))
    if fat >= 0.6:
        return "irritated by repeated ads"
    if tru <= 0.3:
        return "sceptical and guarded"
    felt = emotion.mood_word(st.get("affect"))
    if felt:
        return felt
    if tru >= 0.65 and fam >= 0.2:
        return "curious and receptive"
    if fat >= 0.35:
        return "slightly fatigued"
    return "neutral"


def _feel_step(a: Dict[str, Any], ev: Dict[str, Any], traits_by_agent: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Advance the person's simulated clock to this event, apply its feeling (if any) to the mood; returns the
    stored feeling for the memory item, or None."""
    st = a["state"]
    tr = (traits_by_agent or {}).get(str(ev["agent_id"])) or ev.get("affect_traits") or a.get("affect_traits")
    if not tr:
        tr = emotion.affect_traits({"name": ev.get("name") or str(ev["agent_id"])})
    a["affect_traits"] = tr
    aff = st.get("affect") or emotion.new_affect(tr, 0.0)
    gap = 0.0
    if ev.get("dt_h") is not None:
        try:
            gap = max(0.0, float(ev["dt_h"]))
        except (TypeError, ValueError):
            gap = 0.0
    else:
        gap = emotion.STEP_HOURS.get(str(ev["kind"]), 0.0)
        last_test = (a["memory"][-1].get("test") if a["memory"] else None)
        if last_test and ev.get("test") and last_test != ev.get("test"):
            gap += float(ev.get("gap_h") or emotion.TEST_GAP_H)
    now_h = float(aff.get("t_h") or 0.0) + gap
    feel = emotion.normalize_feel(ev.get("feel"))
    if feel:
        appr = emotion.appraise(feel, tr)
        aff = emotion.update(aff, appr, tr, now_h, brand_directed=ev.get("brand_directed", True),
                             words=feel.get("words", ""), test=str(ev.get("test") or ""), source=str(ev.get("source") or ""))
        stored = {**feel, "emotion": appr["emotion"], "intensity": appr["intensity"], "by": appr["by"],
                  "mismatch": appr["mismatch"]}
    else:
        aff = emotion.current(aff, tr, now_h)
        stored = None
    st["affect"] = aff
    return stored


def record(sim_dir: str, events: Iterable[Dict[str, Any]], scope: str = "default", mode: Optional[str] = None,
           traits_by_agent: Optional[Dict[str, Any]] = None) -> int:
    """events: [{agent_id, test, kind, text, source?, feel?, dt_h?}] -> applied in order; returns how many were stored.
    mode (emotion.mode): 'off' ignores feelings entirely; 'observe' / 'on' keep a mood that fades over simulated time."""
    n = 0
    emo_mode = emotion.mode(mode)
    with _LOCK:
        data = load(sim_dir)
        for ev in events:
            if not isinstance(ev, dict) or ev.get("agent_id") is None or not ev.get("kind"):
                continue
            a = _agent(data, scope, ev["agent_id"])
            fam, fat, tru = TRANSITIONS.get(str(ev["kind"]), (0.0, 0.0, 0.0))
            st = a["state"]
            st["familiarity"] = _clamp(st.get("familiarity", 0) + fam)
            st["fatigue"] = _clamp(st.get("fatigue", 0) + fat)
            st["trust"] = _clamp(st.get("trust", 0.5) + tru)
            stored_feel = _feel_step(a, ev, traits_by_agent) if emo_mode != "off" else None
            if emo_mode != "off":
                data["version"] = 2
            st["mood"] = _derive_mood(st)
            st["energy"] = _clamp(0.8 - 0.5 * st["fatigue"])
            if ev.get("kind") == "abandoned_price":
                st["wallet_pressure"] = _clamp(st.get("wallet_pressure", 0.3) + 0.15)
            ts = ev.get("t") or time.strftime("%Y-%m-%dT%H:%M:%S")
            mem = {"t": ts, "test": str(ev.get("test") or ""),
                   "kind": str(ev["kind"]), "text": str(ev.get("text") or "")[:240], "source": str(ev.get("source") or "")[:80]}
            if stored_feel:
                mem["feel"] = stored_feel
            a["memory"].append(mem)
            a["memory"] = a["memory"][-MAX_MEMORIES:]
            traj = a.setdefault("trajectory", [])
            point = {
                "step": len(traj) + 1,
                "test": str(ev.get("test") or ""),
                "kind": str(ev["kind"]),
                "source": str(ev.get("source") or "")[:80],
                "trust": st["trust"],
                "familiarity": st["familiarity"],
                "fatigue": st["fatigue"],
                "mood": st["mood"],
            }
            if st.get("affect") and emo_mode != "off":
                point["valence"] = st["affect"].get("v")
                point["arousal"] = st["affect"].get("a")
                if stored_feel:
                    point["emotion"] = stored_feel.get("emotion")
            traj.append(point)
            a["trajectory"] = traj[-MAX_MEMORIES:]
            n += 1
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save(sim_dir, data)
    return n


def memories_for(sim_dir: str, agent_id: Any, scope: str = "default", n: int = 5, data: Optional[Dict[str, Any]] = None) -> List[str]:
    """The person's most recent memories as short first-person lines for a prompt."""
    data = data or load(sim_dir)
    a = ((data.get("scopes") or {}).get(scope or "default") or {}).get(str(agent_id))
    if not a:
        return []
    return [m["text"] for m in a["memory"][-n:] if m.get("text")]


def prompt_block(sim_dir: str, agent_id: Any, scope: str = "default", n: int = 5, data: Optional[Dict[str, Any]] = None,
                 mode: Optional[str] = None, brand: str = "") -> str:
    lines = memories_for(sim_dir, agent_id, scope, n, data)
    if not lines:
        return ""
    data = data or load(sim_dir)
    a = ((data.get("scopes") or {}).get(scope or "default") or {}).get(str(agent_id)) or {}
    st = a.get("state") or {}
    feel = ("you are tired of hearing from this brand" if st.get("fatigue", 0) >= 0.5 else
            "you have seen this brand a few times now" if st.get("familiarity", 0) >= 0.3 else "")
    mood = ""
    if emotion.mode(mode) == "on" and st.get("affect"):
        mood = emotion.prompt_line(st["affect"], a.get("affect_traits"), None, brand=brand)
    return ("What already happened to you with this brand (in order, most recent last):\n" + "\n".join(f"- {x}" for x in lines)
            + (f"\n({feel}.)" if feel else "") + "\nStay consistent with that.\n" + (mood + "\n" if mood else ""))


def summary(sim_dir: str, scope: str = "default") -> Dict[str, Any]:
    data = load(sim_dir)
    agents = ((data.get("scopes") or {}).get(scope or "default") or {})
    if not agents:
        return {"people": 0}
    trust = [a["state"].get("trust", 0.5) for a in agents.values()]
    fam = [a["state"].get("familiarity", 0) for a in agents.values()]
    fat = [a["state"].get("fatigue", 0) for a in agents.values()]
    kinds: Dict[str, int] = {}
    mood_counts: Dict[str, int] = {}
    max_steps = 0
    for a in agents.values():
        m_label = str(a["state"].get("mood") or _derive_mood(a["state"]))
        mood_counts[m_label] = mood_counts.get(m_label, 0) + 1
        for m in a["memory"]:
            kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
        max_steps = max(max_steps, len(a.get("trajectory") or []))
    trajectories = []
    for step_idx in range(min(max_steps, 15)):
        step_tr, step_fam, step_fat = [], [], []
        for a in agents.values():
            tr = a.get("trajectory") or []
            if step_idx < len(tr):
                pt = tr[step_idx]
            elif tr:
                pt = tr[-1]
            else:
                continue
            step_tr.append(float(pt.get("trust", 0.5)))
            step_fam.append(float(pt.get("familiarity", 0.0)))
            step_fat.append(float(pt.get("fatigue", 0.0)))
        if step_tr:
            trajectories.append({
                "step": step_idx + 1,
                "avg_trust": round(sum(step_tr) / len(step_tr), 3),
                "avg_familiarity": round(sum(step_fam) / len(step_fam), 3),
                "avg_fatigue": round(sum(step_fat) / len(step_fat), 3),
            })
    return {"people": len(agents), "scope": scope, "avg_trust": round(sum(trust) / len(trust), 3),
            "avg_familiarity": round(sum(fam) / len(fam), 3), "avg_fatigue": round(sum(fat) / len(fat), 3),
            "fatigued_people": sum(1 for x in fat if x >= 0.5),
            "sceptical_people": sum(1 for x in trust if x <= 0.35),
            "moods": mood_counts, "trajectories": trajectories,
            "events": kinds, "scopes": sorted((data.get("scopes") or {}).keys()),
            "emotion": emotion.summarize(data, scope)}


# --------------------------------------------------------------------------
# Test results -> events
# --------------------------------------------------------------------------

def events_from_feed_test(result: Dict[str, Any], brand: str = "the brand") -> List[Dict[str, Any]]:
    names = {c.get("id"): (c.get("name") or c.get("headline") or (c.get("text") or "")[:60]) for c in result.get("creatives") or []}
    out = []
    sessions = result.get("sessions") or []
    first = result.get("seed")
    if first is not None and any("seed" in s for s in sessions):   # seeds are parallel worlds: remember one of them
        sessions = [s for s in sessions if s.get("seed") == first]
    for s in sessions:
        ad = s.get("ad") or {}
        cid, plat = s.get("creative_id"), s.get("platform")
        label = f"the {brand} ad '{names.get(cid, cid)}' on {plat}"
        base = {"agent_id": s.get("agent_id"), "test": "feed_test", "source": f"{cid}#{s.get('exposure')}"}
        if not ad.get("noticed") and not ad.get("stopped"):
            out.append({**base, "kind": "saw_ad", "text": f"You scrolled past {label} without really noticing it."})
            continue
        out.append({**base, "kind": "stopped_on_ad", "text": f"You stopped on {label}" + (f" and thought: {ad['thought']}" if ad.get("thought") else "."),
                    **({"feel": ad["feel"]} if ad.get("feel") else {})})
        if ad.get("click"):
            out.append({**base, "kind": "clicked_ad", "text": f"You tapped {label} to see more."})
        if ad.get("reaction") not in (None, "", "none"):
            out.append({**base, "kind": "reacted_to_ad", "text": f"You reacted '{ad['reaction']}' to {label}."})
        if ad.get("comment"):
            out.append({**base, "kind": "commented_on_ad", "text": f"You commented on {label}: \"{ad['comment'][:140]}\""})
        if ad.get("hide"):
            out.append({**base, "kind": "hid_ad", "text": f"You hid {label}."})
        land = s.get("landing") or {}
        if land.get("feel"):
            done = "signed up" if land.get("completed") else "left without signing up"
            out.append({**base, "kind": "landed_page", "feel": land["feel"],
                        "text": f"You opened the {brand} page from the ad and {done}" + (f": {land['thought']}" if land.get("thought") else ".")})
    return out


def events_from_email_test(result: Dict[str, Any], brand: str = "the brand") -> List[Dict[str, Any]]:
    out = []
    for s in result.get("sessions") or []:
        base = {"agent_id": s.get("agent_id"), "test": "email_test", "source": f"{s.get('email_id')}#step{s.get('step')}"}
        subj = s.get("subject") or "an email"
        if not s.get("opened"):
            out.append({**base, "kind": "received_email", "text": f"An email from {brand} ('{subj}') sat unopened in your inbox."})
            continue
        act = s.get("action")
        kind = {"click": "clicked_email", "reply": "replied_email", "unsubscribe": "unsubscribed", "spam": "marked_spam"}.get(act, "opened_email")
        verb = {"clicked_email": "opened and clicked", "replied_email": "opened and replied to", "unsubscribed": "opened, then unsubscribed from",
                "marked_spam": "marked as spam", "opened_email": "opened and skimmed"}[kind]
        out.append({**base, "kind": kind, "text": f"You {verb} the {brand} email '{subj}'" + (f": {s['reason']}" if s.get("reason") else "."),
                    **({"feel": s["feel"]} if s.get("feel") else {})})
    return out


def events_from_survey(responses: List[Dict[str, Any]], offer: str = "") -> List[Dict[str, Any]]:
    out = []
    for r in responses or []:
        a = r.get("answer") or {}
        if not a:
            continue
        base = {"agent_id": r.get("agent_id"), "test": "survey", "source": "survey"}
        out.append({**base, "kind": "answered_survey",
                    "text": f"A researcher asked about {offer or 'the offer'}; you said you would {a.get('would_convert') or 'maybe'} take it.",
                    **({"feel": a["feel"]} if isinstance(a.get("feel"), dict) else {})})
        if a.get("main_objection"):
            out.append({**base, "kind": "objected", "text": f"Your biggest hesitation then: {a['main_objection'][:160]}"})
    return out


def events_from_pitch(result: Dict[str, Any], brand: str = "the brand") -> List[Dict[str, Any]]:
    out = []
    for r in result.get("people") or []:
        t1 = r.get("turn1") or {}
        if not t1:
            continue
        base = {"agent_id": r.get("agent_id"), "test": "pitch", "source": "pitch"}
        out.append({**base, "kind": "heard_pitch", "text": f"A salesperson from {brand} pitched you; you replied: \"{(t1.get('reply') or '')[:140]}\"",
                    **({"feel": t1["feel"]} if t1.get("feel") else {})})
        if t1.get("walk_away"):
            out.append({**base, "kind": "walked_away", "text": "You told them 'not now' and ended the conversation."})
        t2 = r.get("turn2") or {}
        fin_feel = {"feel": t2["feel"]} if t2.get("feel") else {}
        final = r.get("final_verdict")
        if final == "yes":
            out.append({**base, "kind": "agreed_next_step", "text": "You agreed to the next step they asked for.", **fin_feel})
        elif final == "no":
            out.append({**base, "kind": "declined", "text": "You turned the pitch down.", **fin_feel})
    return out

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
"""

import json
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

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
    return sc.setdefault(str(agent_id), {"state": {"familiarity": 0.0, "fatigue": 0.0, "trust": 0.5}, "memory": []})


def _clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 3)


def record(sim_dir: str, events: Iterable[Dict[str, Any]], scope: str = "default") -> int:
    """events: [{agent_id, test, kind, text, source?}] -> applied in order; returns how many were stored."""
    n = 0
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
            a["memory"].append({"t": ev.get("t") or time.strftime("%Y-%m-%dT%H:%M:%S"), "test": str(ev.get("test") or ""),
                                "kind": str(ev["kind"]), "text": str(ev.get("text") or "")[:240], "source": str(ev.get("source") or "")[:80]})
            a["memory"] = a["memory"][-MAX_MEMORIES:]
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


def prompt_block(sim_dir: str, agent_id: Any, scope: str = "default", n: int = 5, data: Optional[Dict[str, Any]] = None) -> str:
    lines = memories_for(sim_dir, agent_id, scope, n, data)
    if not lines:
        return ""
    data = data or load(sim_dir)
    st = (((data.get("scopes") or {}).get(scope or "default") or {}).get(str(agent_id)) or {}).get("state") or {}
    feel = ("you are tired of hearing from this brand" if st.get("fatigue", 0) >= 0.5 else
            "you have seen this brand a few times now" if st.get("familiarity", 0) >= 0.3 else "")
    return ("What already happened to you with this brand (in order, most recent last):\n" + "\n".join(f"- {x}" for x in lines)
            + (f"\n({feel}.)" if feel else "") + "\nStay consistent with that.\n")


def summary(sim_dir: str, scope: str = "default") -> Dict[str, Any]:
    data = load(sim_dir)
    agents = ((data.get("scopes") or {}).get(scope or "default") or {})
    if not agents:
        return {"people": 0}
    trust = [a["state"].get("trust", 0.5) for a in agents.values()]
    fam = [a["state"].get("familiarity", 0) for a in agents.values()]
    fat = [a["state"].get("fatigue", 0) for a in agents.values()]
    kinds: Dict[str, int] = {}
    for a in agents.values():
        for m in a["memory"]:
            kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    return {"people": len(agents), "scope": scope, "avg_trust": round(sum(trust) / len(trust), 3),
            "avg_familiarity": round(sum(fam) / len(fam), 3), "avg_fatigue": round(sum(fat) / len(fat), 3),
            "fatigued_people": sum(1 for x in fat if x >= 0.5), "events": kinds, "scopes": sorted((data.get("scopes") or {}).keys())}


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
        out.append({**base, "kind": "stopped_on_ad", "text": f"You stopped on {label}" + (f" and thought: {ad['thought']}" if ad.get("thought") else ".")})
        if ad.get("click"):
            out.append({**base, "kind": "clicked_ad", "text": f"You tapped {label} to see more."})
        if ad.get("reaction") not in (None, "", "none"):
            out.append({**base, "kind": "reacted_to_ad", "text": f"You reacted '{ad['reaction']}' to {label}."})
        if ad.get("comment"):
            out.append({**base, "kind": "commented_on_ad", "text": f"You commented on {label}: \"{ad['comment'][:140]}\""})
        if ad.get("hide"):
            out.append({**base, "kind": "hid_ad", "text": f"You hid {label}."})
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
        out.append({**base, "kind": kind, "text": f"You {verb} the {brand} email '{subj}'" + (f": {s['reason']}" if s.get("reason") else ".")})
    return out


def events_from_survey(responses: List[Dict[str, Any]], offer: str = "") -> List[Dict[str, Any]]:
    out = []
    for r in responses or []:
        a = r.get("answer") or {}
        if not a:
            continue
        base = {"agent_id": r.get("agent_id"), "test": "survey", "source": "survey"}
        out.append({**base, "kind": "answered_survey",
                    "text": f"A researcher asked about {offer or 'the offer'}; you said you would {a.get('would_convert') or 'maybe'} take it."})
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
        out.append({**base, "kind": "heard_pitch", "text": f"A salesperson from {brand} pitched you; you replied: \"{(t1.get('reply') or '')[:140]}\""})
        final = r.get("final_verdict")
        if final == "yes":
            out.append({**base, "kind": "agreed_next_step", "text": "You agreed to the next step they asked for."})
        elif final == "no":
            out.append({**base, "kind": "declined", "text": "You turned the pitch down."})
    return out

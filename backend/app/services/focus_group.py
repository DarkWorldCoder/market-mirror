"""Talk to the simulated buyers after the run: one-to-one chat and a moderated focus group.

The OASIS interviews only work while a simulation environment is alive. Here a person is rebuilt from what the run
saved (persona text, decision card, and the behaviour-state memories of what the tests showed or did to them), so a
founder or a sales team can keep asking after the run, the way Ipsos PersonaBot, Native AI or Delve AI offer.

The focus group is built around one known failure: language-model groups drift toward agreement (Ashery, Aiello &
Baronchelli 2024 on emergent conventions; simulated consensus is not evidence of demand). So:
1. every participant gives a private verdict first, before hearing anyone;
2. the moderated discussion runs (each person speaks in turn and sees what was said before);
3. every participant gives a private verdict again.
The report shows the shift between the two private verdicts and flags conformity when opinions converged. Quotes in
the themes are checked against the transcript; participants appear as P1..Pn with their segment, never by name.

This is qualitative exploration of simulated people, not a measurement of real buyers.

Stdlib only; `complete(system, user) -> (text, usage)` is injected.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

VERSION = 1
MAX_PEOPLE = 8
VERDICTS = ["No", "Probably not", "Maybe", "Probably yes", "Yes, definitely"]

Complete = Callable[[str, str], Tuple[str, Dict[str, Any]]]


class Meter:
    def __init__(self, complete: Complete):
        self.complete, self.usage = complete, {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def __call__(self, system: str, user: str) -> str:
        text, u = self.complete(system, user)
        self.usage["calls"] += 1
        for k in ("input_tokens", "output_tokens"):
            self.usage[k] += int((u or {}).get(k) or 0)
        return text


def _bde_text(bde: Any) -> str:
    if not isinstance(bde, dict):
        return ""
    parts = []
    for sec in ("background", "decision_procedure", "evaluation"):
        s = bde.get(sec) if isinstance(bde.get(sec), dict) else {}
        for k, v in s.items():
            if v and k != "discretionary_budget_num":
                parts.append(f"{k.replace('_', ' ')}: {', '.join(map(str, v)) if isinstance(v, list) else v}")
    return "; ".join(parts)[:900]


def rebuild(person: Dict[str, Any], history: str = "") -> str:
    """The system prompt that lets a saved persona speak again (no live simulation needed)."""
    who = ", ".join(str(person[k]) for k in ("age", "gender", "occupation", "city", "country") if person.get(k))
    card = _bde_text(person.get("bde"))
    mem = history or person.get("history") or ""
    return (f"You are {person.get('name') or 'a person'}{f' ({who})' if who else ''}. {str(person.get('persona') or '')[:1800]}\n"
            + (f"How you decide: {card}\n" if card else "")
            + (f"What has happened to you recently: {mem}\n" if mem else "")
            + "Speak as yourself, in your own words, one to three sentences. Be honest: you can be unconvinced, bored, "
              "suspicious or enthusiastic, and you never pretend to know things you have not seen. Do not mention being "
              "simulated.")


def chat(person: Dict[str, Any], message: str, complete: Complete, history: Sequence[Dict[str, str]] = ()) -> str:
    """One reply from one person; `history` = earlier turns [{role: user|person, text}]."""
    turns = "\n".join(f"{'Them' if t.get('role') == 'user' else 'You'}: {t.get('text')}" for t in list(history)[-12:])
    user = (f"The conversation so far:\n{turns}\n\n" if turns else "") + f"Them: {message}\nYou:"
    text, _ = complete(rebuild(person), user)
    return (text or "").strip().strip('"')[:1200]


_VERDICT_RE = re.compile(r"^\W*(yes,? definitely|probably yes|probably not|maybe|no)\b", re.I)
_VERDICT_POS = {"yes definitely": 5, "yes, definitely": 5, "probably yes": 4, "maybe": 3, "probably not": 2, "no": 1}


def _verdict(text: str) -> Optional[int]:
    m = _VERDICT_RE.match(text or "")
    return _VERDICT_POS.get(m.group(1).lower()) if m else None


def _private(people: List[Dict[str, Any]], question: str, ask: Meter, parallel: int, heard: str = "") -> List[Dict[str, Any]]:
    prompt = ((f"You just took part in a group discussion. What was said:\n{heard}\n\n" if heard else "")
              + f"Privately, no one else will see this: {question}\nStart with exactly one of: "
              + " / ".join(VERDICTS) + ", then one sentence why.")

    def one(p):
        try:
            text = ask(rebuild(p), prompt)
        except Exception:  # noqa: BLE001 - a failed answer is recorded as missing
            text = ""
        return {"verdict": _verdict(text), "text": (text or "").strip()[:400]}
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        return list(pool.map(one, people))


THEMES_SYSTEM = "You summarise focus groups for a marketing team. Reply with JSON only."


def _sd(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def shift(pre: List[Optional[int]], post: List[Optional[int]]) -> Dict[str, Any]:
    pairs = [(a, b) for a, b in zip(pre, post) if a is not None and b is not None]
    if not pairs:
        return {"n": 0}
    a, b = [x for x, _ in pairs], [y for _, y in pairs]
    sd_pre, sd_post = _sd(a), _sd(b)
    changed = sum(1 for x, y in pairs if x != y)
    toward = sum(1 for x, y in pairs if abs(y - sum(a) / len(a)) < abs(x - sum(a) / len(a)))
    converged = sd_pre > 0 and sd_post < 0.7 * sd_pre and changed >= len(pairs) / 2
    return {"n": len(pairs), "mean_pre": round(sum(a) / len(a), 2), "mean_post": round(sum(b) / len(b), 2),
            "sd_pre": round(sd_pre, 2), "sd_post": round(sd_post, 2), "changed": changed,
            "moved_toward_group": toward, "conformity_flag": converged,
            "reading": ("Opinions converged during the discussion: read the group's view as social influence inside the "
                        "simulation, and trust the private first answers more." if converged else
                        "Private verdicts did not converge much during the discussion.")}


def run_group(people: List[Dict[str, Any]], guide: Sequence[str], complete: Complete, offer: str = "",
              goal: str = "", rounds: int = 1, parallel: int = 4) -> Dict[str, Any]:
    """Private verdict -> moderated discussion (each guide question, `rounds` passes) -> private verdict -> themes."""
    people = list(people)[:MAX_PEOPLE]
    if len(people) < 2:
        raise ValueError("a focus group needs at least 2 people")
    guide = [str(q).strip() for q in guide if str(q).strip()][:8]
    if not guide:
        raise ValueError("the discussion guide needs at least one question")
    ask = Meter(complete)
    labels = [f"P{i + 1}" for i in range(len(people))]
    segs = [str(p.get("segment") or "") for p in people]
    verdict_q = f"Would you {goal or 'buy or sign up for it'}" + (f" ({offer})" if offer else "") + "?"
    pre = _private(people, verdict_q, ask, parallel)
    transcript: List[Dict[str, Any]] = []

    def said() -> str:
        return "\n".join(f"{t['speaker']}{' (' + t['segment'] + ')' if t.get('segment') else ''}: {t['text']}"
                         for t in transcript[-30:])
    for qi, q in enumerate(guide):
        for r in range(max(1, min(rounds, 3))):
            mod = q if r == 0 else "Did anything you heard change your mind, or does anyone disagree? Say why."
            transcript.append({"q": qi, "speaker": "Moderator", "text": mod})
            order = list(range(len(people)))
            order = order[qi % len(order):] + order[:qi % len(order)]          # rotate who speaks first
            for i in order:
                user = (f"You are in a moderated focus group" + (f" about {offer}" if offer else "") + ". You are "
                        f"{labels[i]}. The discussion so far:\n{said()}\n\nNow it is your turn. Answer the moderator in "
                        "one to three sentences; you may agree or disagree with others.")
                try:
                    text = ask(rebuild(people[i]), user)
                except Exception:  # noqa: BLE001 - a missed turn stays missed
                    continue
                transcript.append({"q": qi, "speaker": labels[i], "segment": segs[i],
                                   "text": (text or "").strip().strip('"')[:600]})
    post = _private(people, verdict_q, ask, parallel, heard=said())
    themes = _themes(transcript, ask, offer)
    participants = [{"id": labels[i], "segment": segs[i], "pre": pre[i]["verdict"], "post": post[i]["verdict"],
                     "pre_text": pre[i]["text"], "post_text": post[i]["text"],
                     "agent_id": people[i].get("agent_id")} for i in range(len(people))]
    return {"version": VERSION, "offer": offer, "goal": goal, "guide": guide, "participants": participants,
            "transcript": transcript, "shift": shift([p["verdict"] for p in pre], [p["verdict"] for p in post]),
            "themes": themes, "usage": ask.usage, "verdict_scale": VERDICTS,
            "note": ("Simulated people in a simulated discussion: qualitative exploration, not a measurement of real "
                     "buyers. Private verdicts were taken before and after the discussion; the shift shows how much the "
                     "group moved them.")}


def affect_split(result: Dict[str, Any], rater: Callable[[List[str]], List[Optional[Dict[str, Any]]]]) -> Dict[str, Any]:
    """How each person felt in private (their verdicts before and after) next to how they sounded in the room, rated
    from their own words by rater (ssr.rate_affect: local embeddings, no model call). Two flags:
    masking: people sound warmer in the room than in private (they hide doubts in public);
    over_convergence: the room's feelings are much more alike than the private ones (the group flattened them).
    Simulated people in a simulated room: a check on the simulation, not a reading of real buyers."""
    parts = result.get("participants") or []
    if len(parts) < 2:
        return {}
    said: Dict[str, List[str]] = {}
    for t in result.get("transcript") or []:
        if t.get("speaker") and t["speaker"] != "Moderator":
            said.setdefault(t["speaker"], []).append(str(t.get("text") or ""))
    texts: List[str] = []
    for p in parts:
        texts += [p.get("pre_text") or "", p.get("post_text") or "", " ".join(said.get(p["id"], []))]
    rated = rater(texts)

    def val(r: Optional[Dict[str, Any]]) -> Optional[float]:
        v = (r or {}).get("valence") if isinstance(r, dict) else None
        return float(v["signed"]) if isinstance(v, dict) and v.get("signed") is not None else None
    rows = []
    for i, p in enumerate(parts):
        pre, post, room = (val(rated[3 * i + k]) for k in range(3))
        rows.append({"id": p["id"], "private_before": pre, "private_after": post, "in_the_room": room,
                     "gap": round(room - post, 3) if room is not None and post is not None else None})
    gaps = [r["gap"] for r in rows if r["gap"] is not None]
    room = [r["in_the_room"] for r in rows if r["in_the_room"] is not None]
    priv = [r["private_after"] for r in rows if r["private_after"] is not None]
    mean_gap = round(sum(gaps) / len(gaps), 3) if gaps else None
    sd_room = round(_sd(room), 3) if len(room) > 1 else None
    sd_priv = round(_sd(priv), 3) if len(priv) > 1 else None
    return {"people": rows, "mean_room_minus_private": mean_gap,
            "sd_in_the_room": sd_room, "sd_private": sd_priv,
            "masking_flag": bool(mean_gap is not None and len(gaps) >= 3 and mean_gap > 0.25),
            "over_convergence_flag": bool(sd_room is not None and sd_priv and len(room) >= 4 and sd_room < 0.5 * sd_priv),
            "scale": "valence -1..1 from the person's own words (SSR anchors)",
            "note": "Simulated feelings, rated from simulated words; not measured emotion."}


def _themes(transcript: List[Dict[str, Any]], ask: Meter, offer: str) -> List[Dict[str, Any]]:
    lines = "\n".join(f"{t['speaker']}: {t['text']}" for t in transcript if t["speaker"] != "Moderator")
    if not lines:
        return []
    try:
        text = ask(THEMES_SYSTEM, f"Focus group{' about ' + offer if offer else ''}. Transcript:\n{lines}\n\n"
                                  "Give up to 5 themes. For each: a short title, whether it is positive, negative or mixed, "
                                  "which participants raised it, and one quote copied word for word. Reply: "
                                  '{"themes": [{"title": "", "tone": "positive|negative|mixed", "who": ["P1"], "quote": ""}]}')
    except Exception:  # noqa: BLE001
        return []
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    hay = re.sub(r"\s+", " ", lines).lower()
    out = []
    for t in (d.get("themes") if isinstance(d, dict) else None) or []:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        q = str(t.get("quote") or "").strip().strip('"')
        out.append({"title": str(t["title"])[:120], "tone": str(t.get("tone") or "mixed")[:10],
                    "who": [str(w) for w in t.get("who") or []][:8],
                    "quote": q if q and re.sub(r"\s+", " ", q).lower() in hay else ""})
    return out[:5]
